#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass

'''
Ingest list of item IDs
Get shape of item
Split shape into files
If the only file available is S3.......?
Get storage ID of file
Send API call to copy file to FROM_S3/CarnegieRepop
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

def get_shape_files(vs, vs_auth, item_id):
	url = f'{vs}API/item/{item_id}?content=shape&tag=original'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	shape_files = response.findall('shape/containerComponent/file')
	if len(shape_files) == 0:
		shape_files = response.findall('shape/binaryComponent/file')
	print(f'Item {item_id} has {len(shape_files)} shape files.')
	return shape_files

def copy_file_to_local(vs, vs_auth, shape_files, item):
	for shape in shape_files:
		if "vxa" not in shape.find('uri').text:
			storage_id = shape.find('storage').text
			print(f'{item} storage ID: {storage_id}')
			filepath = shape.find('path').text
			print(f'{item} filepath: {filepath}')
			file_id = shape.find('id').text
			print(f'{item} file ID: {file_id}')
			copy_url = f'{vs}API/storage/{storage_id}/file/{file_id}/storage/VX-143?move=false&filename=CARNEGIE/{filepath}&priority=MEDIUM'
			headers = {
                'Accept': 'application/xml',
                'Authorization': vs_auth
            }
			copy_response = requests.post(copy_url, headers=headers)
			print(f'Copy status code: {copy_response.status_code}')
			if copy_response.status_code != 200:
				print(f'Error copying file {file_id} to local storage.')
				exit(1)
			else:
				print(f'File {file_id} copied to local storage successfully.')
				return True
	print(f'Item {item} is ONLY on VXA storage. You gotta download from Amazon, sucka!')

def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	item_list = open('itemIds.txt', 'r')
	for item in item_list:
		shape_files = get_shape_files(vs, vs_auth, item.strip())
		copy_file_to_local(vs, vs_auth, shape_files, item.strip())
	return True

main(environment,proxy_config_file,script_file_name)
exit(0)