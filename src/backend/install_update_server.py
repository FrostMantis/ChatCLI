import os
import logging
import subprocess
from mariadb import connect, Error
from dotenv import load_dotenv

import secrets
import string
from pathlib import Path

# ------------------------
# Secrets for defaults
# ------------------------
alphabet = string.ascii_letters + string.digits
flask_key = secrets.token_urlsafe(32)
db_user_pssw = secrets.token_urlsafe(10)

# ------------------------
# Default .env contents
# ------------------------
DEFAULT_ENV = f"""FLASK_ENV=dev
THREADS=2
IGNORE_EMAIL_VERIF=true

# Database credentials
DB_USER=chatcli_access
DB_PASSWORD={db_user_pssw}

ROOT_ACCESS=false
DB_ROOT_USER=root
DB_ROOT_PASSWORD=1234

# Database
DB_NAME=chatcli

# Database Connection
DB_HOST=localhost
DB_PORT=3306

# Email credentials
EMAIL_USER=placeholder
EMAIL_PASSWORD=xx

# Flask secret key
FLASK_SECRET_KEY={flask_key}

#Public URL of the server
PUB_URL=127.0.01
"""

def ensure_env(env=".env"):
    d = Path(__file__).resolve().parent
    envp = d / env
    if not envp.exists():
        envp.write_text(DEFAULT_ENV)
    return envp

# Make sure a .env file exists and load it
ensure_env()
load_dotenv()

# ------------------------
# Logging
# ------------------------
logging.basicConfig(level=logging.INFO)

# ------------------------
# Config
# ------------------------
DB_HOST       = os.getenv("DB_HOST", "localhost")
DB_PORT       = int(os.getenv("DB_PORT", "3306"))
DB_ROOT_USER  = os.getenv("DB_ROOT_USER", "root")
DB_ROOT_PASS  = os.getenv("DB_ROOT_PASSWORD")
DB_NAME       = os.getenv("DB_NAME", "chatcli")
DB_USER       = os.getenv("DB_USER", "chatcli_access")
DB_PASSWORD   = os.getenv("DB_PASSWORD")
raw_root = os.getenv("ROOT_ACCESS", "false").strip().lower()
DB_ROOT_ACCESS = raw_root in ("1", "true", "yes")

# Choose how broad the DB account access should be.
# - For local-only, use: ["localhost", "127.0.0.1"]
# - For containers/remote too, use: ["%"]
HOST_LIST = ["%"]

# Helper to build a safe SQL account literal: 'user'@'host'
def acct_literal(u: str, h: str) -> str:
    u = (u or "").replace("'", "''")
    h = (h or "").replace("'", "''")
    return f"'{u}'@'{h}'"

def create_database_and_tables():
    """Create database and tables if they don't exist, then create/grant the app user."""
    try:
        # 1) Create DB + tables in one connection; autocommit=True for DDL
        if DB_ROOT_ACCESS == True:
            user = DB_ROOT_USER
            password = DB_ROOT_PASS
        else:
            user = DB_USER
            password = DB_PASSWORD
        with connect(host=DB_HOST, port=DB_PORT, user=user, password=password) as conn:
            conn.autocommit = True
            with conn.cursor() as cursor:
                logging.info("Connected to MySQL/MariaDB server as root.")
                if DB_ROOT_ACCESS == True:
                  cursor.execute(
                      f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                      "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                  )
                cursor.execute(f"USE `{DB_NAME}`;")

                table_statements = [
                    # email_subscribers
                    """
                    CREATE TABLE IF NOT EXISTS email_subscribers (
                      id             INT AUTO_INCREMENT PRIMARY KEY,
                      email          VARCHAR(255) NOT NULL UNIQUE,
                      subscribed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # users
                    """
                    CREATE TABLE IF NOT EXISTS users (
                      userID         INT AUTO_INCREMENT PRIMARY KEY,
                      username       VARCHAR(20)  NOT NULL UNIQUE,
                      password       VARCHAR(128) NOT NULL,
                      email          VARCHAR(100),
                      created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
                      email_verified BOOLEAN      DEFAULT FALSE,
                      disabled       BOOLEAN      DEFAULT FALSE,
                      deleted        BOOLEAN      DEFAULT FALSE
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # session_tokens
                    """
                    CREATE TABLE IF NOT EXISTS session_tokens (
                      tokenID        INT AUTO_INCREMENT PRIMARY KEY,
                      userID         INT NOT NULL,
                      session_token  CHAR(64) NOT NULL UNIQUE,  # SHA-256 hex
                      created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
                      expires_at     DATETIME     NOT NULL,
                      revoked        BOOLEAN     DEFAULT FALSE,
                      ip_address     VARCHAR(45),
                      INDEX idx_sess_user (userID)
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # refresh_tokens
                    """
                    CREATE TABLE IF NOT EXISTS refresh_tokens (
                      id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                      userID         INT           NOT NULL,
                      token          CHAR(64)      NOT NULL UNIQUE,  # SHA-256 hex
                      created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      expires_at     DATETIME      NOT NULL,
                      revoked        BOOLEAN       NOT NULL DEFAULT FALSE,
                      INDEX idx_ref_user    (userID),
                      INDEX idx_ref_expires (expires_at),
                      FOREIGN KEY (userID) REFERENCES users(userID)
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # email_tokens
                    """
                    CREATE TABLE IF NOT EXISTS email_tokens (
                      tokenID      INT AUTO_INCREMENT PRIMARY KEY,
                      userID       INT NOT NULL,
                      email_token  CHAR(6)        NOT NULL,  # 6-digit code
                      created_at   DATETIME       DEFAULT CURRENT_TIMESTAMP,
                      expires_at   DATETIME       NOT NULL,
                      revoked      BOOLEAN        DEFAULT FALSE,
                      INDEX idx_email_user (userID)
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # pass_reset_tokens
                    """
                    CREATE TABLE IF NOT EXISTS pass_reset_tokens (
                      tokenID      INT AUTO_INCREMENT PRIMARY KEY,
                      userID       INT NOT NULL,
                      reset_token  CHAR(64)   NOT NULL UNIQUE,  # SHA-256 hex
                      created_at   DATETIME       DEFAULT CURRENT_TIMESTAMP,
                      expires_at   DATETIME       NOT NULL,
                      revoked      BOOLEAN        DEFAULT FALSE,
                      INDEX idx_reset_user (userID)
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # chats
                    """
                    CREATE TABLE IF NOT EXISTS chats (
                      chatID     INT AUTO_INCREMENT PRIMARY KEY,
                      created_at DATETIME          DEFAULT CURRENT_TIMESTAMP,
                      type       ENUM('private','group') NOT NULL DEFAULT 'private',
                      group_name VARCHAR(100) DEFAULT NULL
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # participants
                    """
                    CREATE TABLE IF NOT EXISTS participants (
                      chatID INT NOT NULL,
                      userID INT NOT NULL,
                      archived BOOLEAN DEFAULT FALSE,
                      PRIMARY KEY (chatID, userID),
                      INDEX idx_part_user (userID, chatID),
                      CONSTRAINT fk_participants_chats
                        FOREIGN KEY (chatID) REFERENCES chats(chatID),
                      CONSTRAINT fk_participants_users
                        FOREIGN KEY (userID) REFERENCES users(userID)
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """,

                    # messages
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                      messageID INT AUTO_INCREMENT PRIMARY KEY,
                      chatID    INT NOT NULL,
                      userID    INT NOT NULL,
                      message   TEXT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      edited_at DATETIME,
                      deleted_at DATETIME,
                      INDEX idx_msg_chat_ts (chatID, timestamp)
                    ) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """
                ]

                for stmt in table_statements:
                    cursor.execute(stmt)

                logging.info("All tables created or verified successfully.")

        # 2) Create/grant app user in a fresh connection; autocommit=True
        if DB_ROOT_ACCESS == True:
          with connect(host=DB_HOST, port=DB_PORT, user=user, password=password) as conn:
              conn.autocommit = True
              with conn.cursor() as cursor:
                  for h in HOST_LIST:
                      account = acct_literal(DB_USER, h)

                      # Ensure the user exists, then (re)set its password
                      cursor.execute(f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY %s;", (DB_PASSWORD,))
                      cursor.execute(f"ALTER USER {account} IDENTIFIED BY %s;", (DB_PASSWORD,))

                      # Grant privileges on this database
                      cursor.execute(f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO {account};")

                  # Not strictly required, but harmless:
                  cursor.execute("FLUSH PRIVILEGES;")

                  logging.info(f"User '{DB_USER}' created/updated and granted on `{DB_NAME}` for hosts: {HOST_LIST}")
        else:
            logging.warning("Skipping DB user creation since ROOT_ACCESS is false.")
            input("Press Enter to continue...")

    except Error as e:
        logging.error(f"MySQL Error during setup: {e}")
        input("Press Enter to exit...")
        return

if __name__ == "__main__":
    logging.info("Running database initialization…")
    create_database_and_tables()