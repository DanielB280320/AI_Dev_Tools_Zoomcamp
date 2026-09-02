### List all installed distros
    wsl.exe -l -v

### Destroy distros
    wsl.exe --unregister Ubuntu
    wsl.exe --unregister Debian # and so on

### In Settings > Apps > Apps & Features
- Search for Ubuntu (then Debian, etc), and if something is found, click on uninstall. 
- Search for Linux, and if something is found, click on uninstall on all results
 

### In Start Menu > Turn Windows Features on or off
- Untick Virtual Machine Platform checkbox
- Untick Windows Subsystem for Linux checkbox
 
### Reboot
I might have reboot between step 2) and 3) as well.

### List available distributions
    wsl --list --online

### Install favorite distro
    wsl --install -d Debian

### Set Debian as default
    wsl --set-default Debian
