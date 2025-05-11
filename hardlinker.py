import sqlalchemy
from sqlalchemy.orm import declarative_base, sessionmaker
import qbittorrentapi
import configparser
import os
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(filename='hardlinker.log', level=logging.INFO, format="%(asctime)-15s %(levelname)-8s %(message)s")
logger.info('Started')

# import configurations

config = configparser.ConfigParser()
config.read("config.ini")

torrent_category = config["DEFAULT"]["torrent_category"]
destination_path = config["DEFAULT"]["destination_path"]
origin_path = config["DEFAULT"]["origin_path"]
log_level = config["DEFAULT"].get("log_level", "INFO").upper()
match(log_level):
    case "DEBUG":
        logging.basicConfig(level=logging.DEBUG)
    case "INFO":
        logging.basicConfig(level=logging.INFO)
    case "WARNING":
        logging.basicConfig(level=logging.WARNING)
    case "ERROR":
        logging.basicConfig(level=logging.ERROR)
    case "CRITICAL":
        logging.basicConfig(level=logging.CRITICAL)
    case _:
        logging.basicConfig(level=logging.INFO)
        logging.warning(f"Invalid log level: {log_level}. Defaulting to INFO.")
# DB connection

db_url = "sqlite:///database.db"

engine = sqlalchemy.create_engine(db_url)

Base = declarative_base()

class Torrent(Base):
    __tablename__ = "torrents"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    name = sqlalchemy.Column(sqlalchemy.String)
    status = sqlalchemy.Column(sqlalchemy.String)
    linked = sqlalchemy.Column(sqlalchemy.Boolean)
    hash = sqlalchemy.Column(sqlalchemy.String)
    amount_left = sqlalchemy.Column(sqlalchemy.Integer)
    
Base.metadata.create_all(engine)

Sesssion = sessionmaker(bind=engine)

session = Sesssion()

# QBIT connection

qbt_conn_info = dict(
    host=config["DEFAULT"]["qbt_host"],
    port=config["DEFAULT"]["qbt_port"],
    username=config["DEFAULT"]["qbt_username"],
    password=config["DEFAULT"]["qbt_password"],
)

qbt_client = qbittorrentapi.Client(**qbt_conn_info)

try:
    qbt_client.auth_log_in()
except qbittorrentapi.LoginFailed as e:
    logging.error(f"An error occurred: {e}")

def hard_linker():
    # Get torrents
    
    torrents = qbt_client.torrents_info(category=torrent_category)

    for torrent in torrents:
        # Check by the hash if the torrent already exists in the database
        db_torrent = session.query(Torrent).filter_by(hash=torrent.hash).first()
        if not db_torrent:
            # Create a new Torrent object
            db_torrent = Torrent(
                name=torrent.name,
                status=torrent.state,
                linked=False,
                hash=torrent.hash,
                amount_left=torrent.amount_left
            )
            session.add(db_torrent)
            session.commit()
            logging.info(f"Added torrent {torrent.name} to the database.")
            
        # Update the torrent status if its status has changed
        if db_torrent.status != torrent.state:
            db_torrent.status = torrent.state
            session.commit()
            logging.info(f"Updated torrent {torrent.name} status to {torrent.state}.")
            
        # Check if the amount left is 0
        # Check also if the status is uploading or pausedUP or queuedUP or stalledUP
        if torrent.amount_left == 0 and torrent.state in ["uploading", "pausedUP", "queuedUP", "stalledUP"]:
            # Check if the torrent is already linked
            if not db_torrent.linked:
                # Get the files of the torrent
                files = qbt_client.torrents_files(torrent.hash)
                errored = True
                for file in files:
                    # Check if the file is a .mkv file
                    if file.name.endswith(".mkv"):
                        # Create the destination path
                        dest_path = os.path.join(destination_path, file.name)
                        # Create a hardlink to the file
                        src_path = os.path.join(origin_path, file.name)
                        try:
                            os.link(src_path, dest_path)
                        except FileExistsError:
                            logging.info(f"File {file.name} already exists in {dest_path}.")
                            continue
                        except FileNotFoundError:
                            logging.error(f"File {src_path} not found.")
                            continue
                        except PermissionError:
                            logging.error(f"Permission denied for {src_path}.")
                            continue
                        except OSError as e:
                            logging.error(f"Error creating hardlink for {src_path}: {e}")
                            continue
                        logging.info(f"Created hardlink for {file.name} in {dest_path}.")
                        errored = False
                if errored:
                    logging.error(f"Error creating hardlink for {torrent.name}.")
                    continue
                else:
                    db_torrent.linked = True
                    session.commit()
                    logging.info(f"Linked torrent {torrent.name}.")
            else:
                logging.info(f"Torrent {torrent.name} is already linked.")
        else:
            logging.info(f"Torrent {torrent.name} is not completed yet.")
            
try:
    hard_linker()
except Exception as e:
    logging.error(f"An error occurred: {e}")
finally:
    session.close()
    engine.dispose()
    qbt_client.auth_log_out()
    logging.info("Session closed.")