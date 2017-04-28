# PRConn project Desc
- Pull Request Connector is a intermediate layer application between Github and Jenkins response to Github pull request event 
- Extra parameter can be given in Pull Request issue comment area via format of site: value
- Fork from Leeroy project `https://github.com/litl/leeroy`

# Logging & Debug
- The logging is at default DEBUG level
- Server log file at /var/log/prconn.log
- User FileHandler instead of original StreamHandler, defined in ./logging.conf


# VM instance configuration and installation
- sudo apt-get install python-pip
- sudo apt-get install build-essential python-dev;
required few more packages for the installation of requirements.txt included packages
- sudo apt-get install git; install git client if requred
- sudo pip install -r requirements.txt; 
this will install the required packages includes: Flask, requests, flake8, uwsgi
- sudo python setup.py install;
install the python package from local source code, should be execute in the setup.py folder
- For demo purpose, remember to install Jenkins in your demo server


# Start uWSGI automatically in boot
- /etc/init/prconn.conf defined it
- Start it manually: #sudo start prconn
- Stop it manually: #sudo stop prconn
- Check the Master process and works: #ps aux | grep prconn

# Notes
- More details please refer to Leeroy project readme
