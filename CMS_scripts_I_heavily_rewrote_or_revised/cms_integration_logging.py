import os
import sys
import logging
import platform
import json
from pythonjsonlogger import jsonlogger
from logging.handlers import RotatingFileHandler

# logging module for eng scripts on box

def get_script_name(script_path):
	# get the script file name from the path
	if 'linux' in sys.platform or 'darwin' in sys.platform:
		script_file_name = script_path[script_path.rfind('/')+1:]
	else:
		script_file_name = script_path[script_path.rfind('\\')+1:]
	return script_file_name

def set_up_logging(script_path,env,script_version,log_level):
	# set up logging filenames/paths:
	#script_path = sys.argv[0]
	# get the script file name from the path
	script_file_name = get_script_name(script_path)
	script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
	if 'linux' in sys.platform or 'darwin' in sys.platform:
        	log_path = '/var/log/cms_integrations/'
	else:
    		log_path = script_path[:script_path.rfind('\\scripts\\')]+'\\logs\\'
	log_file = log_path + script_file_name_no_extention + '.log'
	dd_log_file = log_path + script_file_name_no_extention + '_dd.log'
	# create and/or open log files:
	if not os.path.exists(log_file):
		# use with to create the file via open() and it will close automatically
		with open(log_file, 'w'): pass
	if not os.path.exists(dd_log_file):
		# use with to create the file via open() and it will close automatically
		with open(dd_log_file, 'w'): pass
	# get hostname for logging adaptor
	hostname = platform.node()
	if "." in hostname:
		hostname = hostname[:hostname.find('.')]
	#start logger
	logger = logging.getLogger()
	# decide logging level
	if log_level == 'INFO':
		logger.setLevel(logging.INFO)
	elif log_level == 'WARN':
		logger.setLevel(logging.WARN)
	elif log_level == 'ERROR':
		logger.setLevel(logging.ERROR)
	elif log_level ==  'DEBUG':
		logger.setLevel(logging.DEBUG)
	else:
		logger.setLevel(logging.DEBUG)
	# setup logger
	#lf = logging.FileHandler(log_file)
	lf = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5) # 10 MB, 5 files
	lf.setFormatter(logging.Formatter('%(asctime)s [host: {}] [environment: {}] [scriptname: {}] [script_version: {}] [thread: %(thread)d] [level: %(levelname)s] %(message)s'.format(hostname,env,script_file_name,script_version)))
	#lfdd = logging.FileHandler(dd_log_file)
	lfdd = RotatingFileHandler(dd_log_file, maxBytes=10000000, backupCount=5) # 10 MB, 5 files
	formatter = jsonlogger.JsonFormatter('%(asctime)s %(thread)d %(levelname)s %(message)s')
	lfdd.setFormatter(formatter)
	logger.addHandler(lf)
	logger.addHandler(lfdd)
	return logger
