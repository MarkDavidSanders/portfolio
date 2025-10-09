#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import shutil
import sys
import logging
import os
import getpass

'''
Ingest list of item IDs
Get shape of item
Split shape into files
Locate VX-266 file
Get path of VX-266 file
Copy file to watch folder
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
	profile = sys.argv[2]
		
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

def get_local_file_path(vs, vs_auth, item_id):
	url = f'{vs}API/item/{item_id}?content=shape&tag=original'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	shape_files = response.findall('shape/containerComponent/file')
	mac_path = None
	for file in shape_files:
		if file.find('storage').text == 'VX-266':
			mac_path = file.find('uri').text
			file_name = file.find('path').text[17:]
	if mac_path is None:
		print(f'{item_id} does not have a file in staging!')
		exit(1)
	else:
		# windows_path = mac_path.replace("file:///mnt/Mezz","M:").replace("/","\\")
		file_path = mac_path.replace("file://", "")
		print(f'Local file for {item_id} is:\n{file_path}')
		return file_path, file_name

def copy_file_to_watch_folder(file_path, file_name, profile):
	# destination = rf'M:\vodstorage\transcoding\elemental\Ateme_Redux\{profile}\{file_name}'
	destination = rf'/mnt/Mezz/vodstorage/transcoding/elemental/Ateme_Redux/{profile}/{file_name}'
	shutil.copyfile(file_path, destination)
	return True

def main(environment,proxy_config_file,script_file_name,profile):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	item_list = open('itemIds.txt', 'r')
	for item in item_list:
		file_path, file_name = get_local_file_path(vs,vs_auth,item.replace('\n',''))
		if copy_file_to_watch_folder(file_path, file_name, profile):
			print(f'Copied {file_name} to {profile} folder')
		else:
			print(f'Failed to copy {file_path} to {profile} folder')
			exit(1)
	return True

main(environment,proxy_config_file,script_file_name,profile)
exit(0)