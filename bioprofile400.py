"""
scriptet kræver en python3 kompatible version af astm_seriel som jeg har lavet
"""

import astm_serial
import pandas as pd
from time import sleep
from datetime import datetime
from astm_serial.client import AstmConn
from os import popen
import logging


fh = logging.FileHandler('bioprofile400.log')
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
logger = logging.getLogger('astm_logger')
logger.setLevel(logging.DEBUG)
logger.addHandler(fh)
logger.addHandler(ch)

logger.info("opening port")
astm = AstmConn(port='/dev/ttyUSB0', timeout=1)
logger.info("open. Listening.")

external_file_path = '/home/laeb/od/CFB-CHO/core/Bioprocess/Bioprofile400/exports/'
local_file_path = "/home/miksch/Desktop/data/"

while True:
    message = []
    blank_line_count = 0
    while blank_line_count<3:
        a = astm.get_data()
        if a:
            if len(message)==0:
                logger.info("new message arriving")
            message.append(a)
            try:
                logger.debug(a.decode())
            except UnicodeDecodeError as e:
                logger.debug("warning: not unicode")
        else:
            blank_line_count+=1
            if blank_line_count==3 and len(message)!=0:
                logger.info(f"message finished. {len(message)} lines.")
                if len(message)>3:
                    logger.info("writing to file")                                         
                    file_name = str(datetime.now().isoformat()).replace(":", "_") + ".csv"
                    pd.DataFrame([x.decode().split("|") for x in message]).to_csv(local_file_path+file_name, index=False)
                    sleep(1)
                    try:
                        logger.info(f"trying to move data to {external_file_path+file_name}")
                        popen(f"mv {local_file_path+file_name} {external_file_path+file_name}")
                    except:
                        logger.error(f"failed to write external file: {external_file_path+file_name}")
    sleep(1)

