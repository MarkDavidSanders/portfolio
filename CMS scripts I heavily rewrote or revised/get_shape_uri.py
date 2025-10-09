#!/usr/bin/python3
# script version and log level
script_version = "250123.10"
log_level = "DEBUG" # DEBUG INFO WARN ERROR
'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Shape tag
3. Environment

WHAT THE SCRIPT DOES:
-Gets secrets from Vault
-Sends URI call to Vidispine
-Searches list of URIs for local path
-Returns local URI if there is one
-Returns empty string if not
'''
###CHANGE LOG###
'''
version 250123.10 - initial version
'''

#native imports
import requests
import sys
import traceback

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
    item_id = sys.argv[1]
    shape_tag = sys.argv[2]
    env = sys.argv[3].lower()
else:
	if len(sys.argv) > 4:
		arg_problem = "Too many args provided!"
	else:
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
logger.info(f'{item_id} provided as the item.', extra=extras)
logger.info(f'{shape_tag} provided as the shape tag.', extra=extras)

#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions:
def get_uris(vs, token, item_id, shapetag):
	url = f'{vs}API/item/{item_id}/uri?tag={shapetag}'
	headers = {
		'Accept': f'application/json',
		'Authorization': f'token {token}'
	}
	try:
		response = requests.get(url, headers=headers, verify=crt_file)
		response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful
		uri_list_doc = response.json()
	except HTTPError as http_err:
		logger.error(f'HTTP error occurred: {http_err}', extra=extras)
		exit(1)
	except Exception as err:
		logger.error(f'Other error occurred: {err}', extra=extras)
		exit(1)
	uri_list = []
	if "uri" in uri_list_doc:
		for uri in uri_list_doc["uri"]:
			uri_list.append(uri)
		return uri_list
	else:
		logger.info(f"Shape tag {shapetag} not found in item {item_id}")
		return False
	
def main():
	# get_vault_secret_data function returns a dict  
	secret_path = f'v1/secret/{env}/vidispine/vantage'
	vs_secret_data = eng_vault_agent.get_secret(secret_path)
	username = vs_secret_data["username"]
	password = vs_secret_data["password"]
	vs = vs_secret_data["api_url"]
	vs_auth = eng_vs_token.get_basic_auth(username,password)
	auto_refresh = 'false'
	ttl = 10
	token_data = eng_vs_token.get_token_no_auto_refresh(vs, vs_auth, ttl)
	if token_data:
		token = token_data["token"]
	else:
		logger.error("Didn't get token data from vidispine?")
		exit(2)
	uri_list = get_uris(vs, token, item_id, shape_tag)
	if not uri_list:
		sys.stdout.write('')
		return True
	else:
		for uri in uri_list:
			if uri.startswith('file:///mnt/Mezz'):
				sys.stdout.write(uri)
				return True
		for uri in uri_list:
			if uri.startswith('file'):
				sys.stdout.write(uri)
				return True
		
try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)
