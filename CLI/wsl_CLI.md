## list all installed distros
    wsl.exe -l -v

## destroy distros
    wsl.exe --unregister Ubuntu
    wsl.exe --unregister Debian # and so on

### In Settings > Apps > Apps & Features
    search for Ubuntu (then Debian, etc), and if something is found, click on uninstall
    search for Linux, and if something is found, click on uninstall on all results
 

### In Start Menu > Turn Windows Features on or off
    Untick Virtual Machine Platform checkbox
    Untick Windows Subsystem for Linux checkbox
 
### Reboot
    I might have reboot between step 2) and 3) as well.

## list available distributions
    wsl --list --online

## install favorite distro
    wsl --install -d Debian

## set Debian as default
    wsl --set-default Debian
