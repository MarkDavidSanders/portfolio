#!/usr/bin/python3
import requests
import sys
import logging
import os
import getpass
import json

'''
PREP WORK: Create/export Ateme template JSON files and place them all in the dedicated folder specified by the path variable.
BE SURE TO INCLUDE TEMPLATE NAME/ID VALUES!
'''
path = '/mnt/Mezz/ADMIN/ateme_batch_staging'
'''
HOW THE SCRIPT WORKS:
-Sets up global access variables based on environment
-Generates a bearer token via POST call and binds it to a variable
-Compiles list of JSON files in the "path" folder
-Runs a POST call for each file, using the content of that file to create an Ateme template
-Cancels bearer token via DELETE call
-Gangsta gangsta
'''

def get_ateme_env():
	# this function asks the user to enter the environment name
	# Ateme is only set up in PROD and DEV, so UAT is not a valid option
	env = raw_input('\nWhich Ateme environment are we working on today? (dev, prod)\n\n') # type: ignore
	if env.lower() == 'dev' or env.lower() == 'prod':
		print('\nWe will be working on: %s.\n' % env)
		return env
	else:
		print('\nOops try again. Must be dev or prod.\n')
		get_ateme_env()

# check if an environment argument was passed to the script; ask for input if not

if len(sys.argv) == 1:
	# sys.argv[0] is always the script's path so that would count as the one argument
	# so we know the argument was not passed
	environment = get_ateme_env()
else:
	# len != 1 so argument was passed
	environment = sys.argv[1]
	environment = environment.lower()
	if environment not in ["prod","dev"]:
		print('\nArgument was neither dev nor prod.\nArgument passed: %s\n' % sys.argv[1])
		environment = get_ateme_env()

# logging setup

script_path = sys.argv[0]
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')

if not os.path.exists(log_file):
	# use with to create the file via open() and it will close automatically
	with open(log_file, 'w'): pass

logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# set up other global variables

if environment == 'prod':
		url_template = 'https://ind-ateme.indemand.com/tf2181/api/templates/'
		url_token = 'https://ind-ateme.indemand.com/tf2181/users/token'
		url_cancel = 'https://ind-ateme.indemand.com/tf2181/users/logout'
		password = 'IndAteme2024!'
elif environment == 'dev':
		url_template = 'https://dev-ateme.indemand.com/tf2181/api/templates/'
		url_token = 'https://dev-ateme.indemand.com/tf2181/users/token'
		url_cancel = 'https://dev-ateme.indemand.com/tf2181/users/logout'
		password = 'DevAteme2024!'

# functions

def get_token(environment):
	headers = {
		'Accept': 'application/json',
		'Content-type': 'application/json',
		}
	data = {
			'username': 'admin',
			'password': password
		}
	response = requests.post(url_token, headers=headers, json=data)
	json_response = response.json()
	try:
		return json_response['access_token']
	except KeyError:
		print('Something went wrong. Response code: ' + str(response.status_code))
		exit(1)

def get_jsons():
	file_list = []
	for x in os.listdir(path):
		if x.endswith('.json') and not x.startswith('.'):
			file_list.append(x)
	print('Number of templates to be created: %s\n' %str(len(file_list)))
	return file_list

def create_templates(token):
	headers = {
		'Content-type': 'application/json',
		'Authorization': 'Bearer %s' %str(token)
		}
	for file in get_jsons():
		with open(file) as f:
			template = json.load(f)
		response = requests.post(url_template, headers=headers, json=template)
		if response.status_code == 201:
			logging.info('%s: post status: %s' % (environment,str(response.status_code)))
			print('Template created: %s\n') %template['name']
		else:
			logging.error('%s: post status: %s content: %s' % (environment,str(response.status_code),response.content))
			print('Response code: ' + str(response.status_code))
			exit(1)
	cancel_response = requests.delete(url_cancel, headers=headers)
	if cancel_response.status_code == 200:
		print("DONE. Don't forget to get your files out of the staging folder!\n")
	else:
		print('Token cancellation response code: ' + str(response.status_code))
	return True

def main(environment):
	user = getpass.getuser()
	logging.info('%s: COMMENCING: %s executed by %s' % (environment,script_file_name,user))

	os.chdir(path)
	create_templates(get_token(environment))

	return True

main(environment)
exit(0)