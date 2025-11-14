#!/usr/bin/python3
# script version and log level
script_version = "240611.10"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
PREP WORK: Edit existing Ateme templates, save them as JSON files, and place them all in the dedicated folder specified by the path variable.
BE SURE THE ID VALUE IN EACH JSON IS PRESENT/CORRECT!

HOW THE SCRIPT WORKS:
-Sets up global access variables based on environment
-Generates a bearer token via POST call and binds it to a variable
-Compiles list of JSON files in the "path" folder
-Runs a PUT call for each file, using the content of that file to update an existing Ateme template
-Cancels bearer token via DELETE call
-Gangsta gangsta
'''

###CHANGE LOG###
'''
version 240611.10 - initial version
'''

#native imports
import os
import getpass
import json
import sys
import traceback
import requests
from requests.exceptions import HTTPError

# custom support packages live in the scripts/packages/ directory
# add path to packages for import
script_path = sys.argv[0]
if 'linux' in sys.platform or 'darwin' in sys.platform:
    packages_path = script_path[:script_path.rfind('/scripts/')]+'/packages/'
    staging_path = '/mnt/Mezz/ADMIN/ateme_batch_staging'
else:
    packages_path = script_path[:script_path.rfind('\\scripts\\')]+'\\packages\\'
    staging_path = 'M:\\ADMIN\\ateme_batch_staging'
sys.path.insert(0,packages_path)

# add variable for path to crt_file (DigiCertCA.crt) which is in the packages path above
crt_file = packages_path + 'DigiCertCA.crt'

# import logging module
import cms_integration_logging # need this for everything

# args to variables:
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
if len(sys.argv) == 1:
	# sys.argv[0] is always the script's path so that would count as the one argument
	# so we know the argument was not passed
	print("This script needs the environment argument!")
	exit(1)
else:
	env = sys.argv[1]
	env = env.lower()
	environment = env

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args.

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)

#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs # vs tools

# ateme endpoints:
template_endpoint = 'api/templates/'
token_endpoint = 'users/token'
cancel_endpoint = 'users/logout'

# functions

def get_token(username,password,base_url):
	headers = {
		'Accept': 'application/json',
		'Content-type': 'application/json',
		}
	data = {
			'username': username,
			'password': password
		}
	url_token = base_url + token_endpoint
	response = requests.post(url_token, headers=headers, json=data)
	json_response = response.json()
	try:
		return json_response['access_token']
	except KeyError:
		print('Something went wrong. Response code: ' + str(response.status_code))
		exit(1)

def get_jsons():
	file_list = []
	for x in os.listdir(staging_path):
		if x.endswith('.json') and not x.startswith('.'):
			file_list.append(x)
	print('Number of templates to be modified: %s\n' %str(len(file_list)))
	return file_list

def edit_templates(base_url,token):
	headers = {
		'Content-type': 'application/json',
		'Authorization': 'Bearer %s' %str(token)
		}
	for file in get_jsons():
		with open(file) as f:
			template = json.load(f)
			try:
				update_url = base_url + template_endpoint + template['id']
			except KeyError:
				print('ID value not found in %s!') %file
		response = requests.put(update_url, headers=headers, json=template)
		if response.status_code == 201:
			logger.info(f'{environment}: put status: {response.status_code}')
			print(f'Template updated: {template["name"]}\n')
		else:
			logger.error('%s: put status: %s content: %s' % (environment,str(response.status_code),response.content))
			print('Response code: ' + str(response.status_code))
			exit(1)
	url_cancel = base_url + cancel_endpoint
	cancel_response = requests.delete(url_cancel, headers=headers)
	if cancel_response.status_code == 200:
		print("DONE. Don't forget to get your files out of the staging folder!\n")
	else:
		print('Token cancellation response code: ' + str(response.status_code))
	return True

def main():
	# get_vault_secret_data function returns a dict  
	secret_path = f'v1/secret/{env}/ateme/vantage'
	secret_data = eng_vault_agent.get_secret(secret_path)
	username = secret_data["username"]
	password = secret_data["password"]
	base_url = secret_data["api_url"]
	os.chdir(staging_path)
	edit_templates(base_url,get_token(username,password,base_url))
	return True

try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)