#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import time
import sys
import logging
import os
import getpass

'''
Ingest list of item IDs
Get shape of item
Split shape into files
Locate VX-266 file(s)
If uri contains "%0D", delete that file
'''

def get_env():
	# this function asks the user to enter the environment name
	print()
	env = input('Enter the environment we are restarting failed proxies on: (dev, uat, prod)\n')
	env = env.lower()
	if env == 'dev' or env == 'uat' or env == 'prod':
		print(f'\nThank you kind sir/madam for your most generous and enlightening instructions. We will be working on: {env}.\n')
		return env
	else:
		print('\noops try again. must be dev, uat, or prod\n')
		get_env()
		
# check if an environment arguement was passed to the script, if not ask for input

if len(sys.argv) == 1:
	# sys.argv[0] is always the script's path so that would count as the one argument
	# so we know the argument was not passed - ask for user input
	environment = get_env()
else:
	# more than one argument was passed so lets see if the format is good
	environment = sys.argv[1]
	environment = environment.lower()
	if environment not in ["prod","dev","uat"]:
		# format of the enviroment argument wasn't good, ask for user input
		print()
		print('Argument passed to script was not an environment name: dev, uat, or prod')
		print(f'Argument passed: {sys.argv[1]}')
		print()
		environment = get_env()
		
script_path = sys.argv[0]
# get the script file name from the path
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')
proxy_config_file = script_path.replace(script_file_name,'proxy_config.xml')

if not os.path.exists(log_file):
	# use with to create the file via open() and it will close automatically
	with open(log_file, 'w'): pass

logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# functions

def xml_prep(res):
	# prepare a VS xml for parsing with ET
	res = res.content
	res = res.decode(encoding='utf-8', errors='strict')
	# because I hate dealing with the namespace in ET
	res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
	res = res.encode(encoding='utf-8', errors='strict')
	res = ET.fromstring(res)
	return res

def get_variables_from_config(environment,proxy_config):
	env = proxy_config.findall('environment')
	for e in env:
		if e.find('short_name').text == environment:
			vs = e.find('vidispine/ip_address').text
			vs_auth = e.find('vidispine/auth').text
			break
	return vs,vs_auth

def get_bad_local_file_path(vs, vs_auth, item_id):
	url = f'{vs}API/item/{item_id}?content=shape&tag=original'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	shape_files = response.findall('shape/containerComponent/file')
	for file in shape_files:
		if file.find('storage').text == 'VX-266':
			file_id = file.find('id').text
			file_uri = file.find('uri').text
			# file_path = file_uri.replace('file:///mnt/Mezz/mam/prod/staging/','')
			if "%0D" in file_uri:
				field_list = file.findall('metadata/field')
				for field in field_list:
					if field.find('key').text == '__deletion_lock_id':
						lock_id = field.find('value').text
						return file_id, lock_id
	return False, False
				
def delete_deletion_lock_and_file(vs, vs_auth, item_id, file_id, lock_id):
	lock_url = f'{vs}API/deletion-lock/{lock_id}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	lock_response = requests.delete(lock_url, headers=headers)
	if lock_response.status_code != 204:
		print(f'Something went wrong deleting deletion lock {lock_id} for item {item_id}!')
		exit(1)
	print(f'Successfully deleted deletion lock {lock_id} for item {item_id}.')
	time.sleep(5)
	file_delete_url = f'{vs}API/storage/file/{file_id}'
	file_delete_response = requests.delete(file_delete_url, headers=headers)
	if file_delete_response.status_code != 200:
		print(f'Something went wrong deleting file {file_id} for item {item_id}!')
		exit(1)
	print(f'Successfully deleted file {file_id} for item {item_id}.\n\n\n')
	return True

def move_file(vs, vs_auth, file_id, corrected_file_path):
	url = f'{vs}API/storage/VX-266/file/{file_id}/storage/VX-266?move=true&priority=HIGH&filename={corrected_file_path}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = requests.post(url, headers=headers)
	if response.status_code == 200:
		print(f'Successfully moved file {file_id} to {corrected_file_path}')
		return True
	else:
		print(f'Something went wrong moving file {file_id} to {corrected_file_path}')
		exit(1)

def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	item_list = open('itemIds.txt', 'r')
	for item in item_list:
		item_id = item.strip()
		bad_file_id, bad_lock_id = get_bad_local_file_path(vs, vs_auth, item_id)
		if not bad_file_id:
			print(f'Item {item_id} does not have a bad file! Inspect manually to be sure.\n')
		else:
			print(f'Item {item_id} bad file ID: {bad_file_id} and lock ID: {bad_lock_id}')
			delete_deletion_lock_and_file(vs, vs_auth, item_id, bad_file_id, bad_lock_id)
	return True

main(environment,proxy_config_file,script_file_name)
exit(0)