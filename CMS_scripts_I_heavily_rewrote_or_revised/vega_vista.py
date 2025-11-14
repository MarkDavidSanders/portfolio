#!/usr/bin/env python3
# -*- coding: utf-8 -*-
script_version = "250130.11"
log_level = "INFO" # DEBUG INFO WARN ERROR
"""
Created on Tue Oct 19 14:00:47 2021

@author: Jacob

ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. File Path
3. Transcode Profile
4. Vega Vista Output Path
5. Environment

WHAT THIS SCRIPT DOES:
-Submits the item to VV using script args as parameters
"""
###CHANGE LOG###
'''
version 211019.14 - initial version
version 250130.11 - CMS Integration
'''

#native imports
import subprocess
import sys
import time

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
if len(sys.argv) == 6:
    item_id = sys.argv[1]
    video_path = sys.argv[2]
    config = sys.argv[3]
    output_path = sys.argv[4]
    env = sys.argv[5].lower()
else:
	if len(sys.argv) > 6:
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

#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions
def mezz_path_convert(path):
    ''' Input path to convert to linux
        Output linux path on Mezz'''
    return path.replace('M:', '/mnt/Mezz').replace('\\','/')

def arg_dict(video_path, config, output_path):
    '''Output a dictionary of arguments received'''
    video_path_linux = mezz_path_convert(video_path).replace(" ", "\ ")
    config_path = f'/mnt/Mezz/mam/admin/integrations/vegavista_cfgs/{env}/{config}.cfg'
    output_path_linux = mezz_path_convert(output_path)
    
    return {'item_id':item_id, 'video_path':video_path_linux, 'config_path':config_path, 'output_path':output_path_linux, 'env':env} 

def environment(args):
    '''Input arguments
        Output vega vista servers as a list'''
    if args['env'] == 'prod':
        server = ['vegavista01', 'vegavista02', 'vegavista03', 'vegavista04']
    elif args['env'] == 'uat':
        server = ['vegavista-uat']
    else:
        server = ['vegavista-dev']  
    return server

def responses(item_id, stdout, env):
    '''Input item_id and stdout from plink
        Output code repsonses and vega vista message as a list'''
    if "exit code = 0" in str(stdout):
        code = 0
        message = f'{env} {item_id} Success - No Errors and warnings found in the stream'
        logger.warning(message)
    elif 'exit code = 1' in str(stdout):
        code = 1
        message = f'{env} {item_id} Failure - Errors found in the stream'
        logger.warning(message)
    elif "exit code = 2" in str(stdout):
        code = 2
        message =f'{env} {item_id} Failure - Warnings found in the stream'
        logger.warning(message)
    elif 'exit code = 3' in str(stdout):
        code = 3
        message = f'{env} {item_id} Failure - Errors and Warnings found in the stream'
        logger.warning(message)
    elif 'licenses in use' in str(stdout):
        code = 99
        message = f'All {env} licenses in use'
        logger.error(message)
    else:
        code = None
        message = 'Unknown error'
        logger.error(message)
        logger.error(stdout)
    return [code,message]

def plink(args, user, key, server_instance):
    '''Input args (a list), user, location of the ssh key, and server (a list)
        Runs vegavista via plink
        Outputs stdout from vega vista server'''
    plink_exe = r'"C:\Program Files\PuTTY\plink.exe"'
    server = environment(args)   
    
    logger.warning(f'Submitting {args["item_id"]} to {server[server_instance]}')
    
    command=f"~/VegaVista/./VegaVista {args['video_path']} {args['config_path']} {args['output_path']} \n"
    plink = f'{plink_exe} -ssh -batch {user}@{server[server_instance]} -i {key} {command}'

    proc = subprocess.Popen(plink, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    stdout, stderr = proc.communicate(command.encode())
    
    return stdout
 
def main(args):
    '''Input args from command line
        Attempts DEV/UAT submission 4 times
        Attempts PROD submission to each node consecutively as licenses are used (4 times)
        Output message for vantage'''

    user ='xsanadmin'
    key = 'C:\\Users\\xsanadmin\\.ssh\\vantage.ppk'
    
    server_instance = 0
    count = 0
    
    while count < 4:
        output = plink(args, user, key, server_instance)
        code = responses(args['item_id'], output, args['env'])
        
        if code[0] == 99 or code[0] == None:
            if args['env'] == 'dev' or args['env'] == 'uat':
                count +=1
                time.sleep(30)
                
            elif args['env'] == 'prod':
                if server_instance < 4:
                    server_instance += 1
                if server_instance == 4:
                    server_instance = 0
                    count +=1
                    time.sleep(30)
            
        else:
            return code[1]
        
    logger.error((f'Unable to submit to {args["env"]} Vega Vista'))        
    exit(1)

args = arg_dict(video_path, config, output_path)

vantage_msg = main(args)
sys.stdout.write(vantage_msg)

exit(0)