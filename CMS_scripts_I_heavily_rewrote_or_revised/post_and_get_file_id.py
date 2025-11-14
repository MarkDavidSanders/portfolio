#!/usr/bin/python3
# script version and log level
script_version = "250122.10"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. VS Storage ID
2. VS File Path
3. Environment

WHAT THIS SCRIPT DOES:
-Gets VS secrets from Vault
-Constructs a POST call to give the file a VS File ID
	-If file is _not_ SCC, adds parameter "&createOnly=False" to POST call
-Sends call
	-If response code is not 409, parse the XML response to get the file ID
	-If response code is 409, the file already has an ID
		-Sends a GET call to get the file ID
-Writes the file ID to stdout
-If file ID can't be found, return 0
'''
###CHANGE LOG###
'''
version 250122.10 - initial version
'''

#native imports
import sys
import traceback
import requests
import xml.etree.ElementTree as ET

# custom support packages live in the scripts/packages/ directory
# add path to packages for import
script_path = sys.argv[0]
if 'linux' in sys.platform or 'darwin' in sys.platform:
    packages_path = script_path[:script_path.rfind('/scripts/')]+'/packages/'
else:
    packages_path = script_path[:script_path.rfind('\\scripts\\')]+'\\packages\\'
sys.path.insert(0,packages_path)

# add variable for path to crt_file (DigiCertCA.crt) which is in the packages path above
crt_file = packages_path + 'DigiCertCA.crt'

# import logging module
import cms_integration_logging # need this for everything

# args to variables:
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 4:
	vs_storage_id = sys.argv[1]
	file_path = sys.argv[2]
	env = sys.argv[3].lower()
else:
	if len(sys.argv) > 4:
		arg_problem = "Too many args provided!"
	elif len(sys.argv) < 4:
		arg_problem = "Not enough args provided!"
            
# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{file_path} provided as the file path.', extra=extras)
logger.info(f'{vs_storage_id} provided as the storage id.', extra=extras)

#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions		
def main():
	# get_vault_secret_data function returns a dict
	secret_path = f'v1/secret/{env}/vidispine/vantage'
	vs_secret_data = eng_vault_agent.get_secret(secret_path)
	username = vs_secret_data["username"]
	password = vs_secret_data["password"]
	vs = vs_secret_data["api_url"]
	vs_auth = eng_vs_token.get_basic_auth(username,password)
	ttl = 10
	token_data = eng_vs_token.get_token_no_auto_refresh(vs, vs_auth, ttl)
	if token_data:
		token = token_data["token"]
		file_id = 0
		# try post first
		post_url = f'{vs}API/storage/{vs_storage_id}/file?path={file_path}&state=CLOSED&createOnly=false'
		headers = {
			'Authorization': f'token {token}'
		}
		post_response = requests.post(post_url, headers=headers, verify=crt_file)
		if post_response.status_code == 409:
			logger.info('File conflict. Trying GET.')
			# try get
			get_url = f'{vs}API/storage/{vs_storage_id}/file?path={file_path}'
			get_response = requests.get(get_url, headers=headers, verify=crt_file)
			if get_response.status_code == 200:
				file_doc = eng_vs_token.xml_prep(get_response)
			else:
				logger.error(f'Something went wrong. File ID not found.')
		elif post_response.status_code == 200:
			# post worked
			logger.info(f'POST response code {post_response.status_code}')
			file_doc = eng_vs_token.xml_prep(post_response)
		else:
			logger.error(f'Something went wrong. File ID not found.')
		try:
			file_id = file_doc.find('id').text
		except:
			file_id = 0
		logger.info(f'file id {file_id}')
		sys.stdout.write(str(file_id))
		return True
	else:
		logger.error("Didn't get token data from vidispine?")
		exit(2)

try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)