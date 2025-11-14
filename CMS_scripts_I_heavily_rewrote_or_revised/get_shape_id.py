#!/usr/bin/python3
# script version and log level
script_version = "250121.10"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Shape tag
3. Environment

WHAT THIS SCRIPT DOES:
-Gets secrets from Vault
-Constructs an API call for the item's tagged shape
-Returns the ID for that shape
'''
###CHANGE LOG###
'''
version 250121.16 - initial version
'''

#native imports
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
		# get_shape_ids returns a list that may or may not have an ID in it
		shape_ids = eng_vs_token.get_shape_ids(vs, token, item_id, shape_tag)
		if len(shape_ids) != 0:
			sys.stdout.write(shape_ids[0])
		else:
			sys.stdout.write('')
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
