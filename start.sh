#!/bin/bash

COLOR_YELLOW="\033[0;33m"
COLOR_GREEN="\033[0;32m"
COLOR_RED="\033[0;31m"
COLOR_CYAN="\033[0;36m"
COLOR_END="\033[0m"

SCRIPT=$(readlink -f "$0")
FOLDER=$(dirname "${SCRIPT}")
cd "${FOLDER}"

OUTPUT="${FOLDER}/output"

NETWORK_DRIVE=""


echo; echo
# `test -e` is used to detect cases where the connection has been lost
if grep -q "${OUTPUT}" /proc/mounts && test -e "${OUTPUT}";
then
    echo -e "${COLOR_GREEN}Network folder is already mounted!${COLOR_END}"
else
    echo -e "${COLOR_YELLOW}Network folder is not online. Starting setup ..${COLOR_END}"
    echo; echo

    # To simplify usage, we split asking for the root password into its own step
    echo -e "${COLOR_YELLOW}Testing for root access; please enter the password for THIS PC if asked${COLOR_END}"
    while ! sudo true;
    do
        echo -e "${COLOR_RED}Failed to get password. Please try again ..${COLOR_END}"
    done

    echo -e "${COLOR_GREEN}OK! Password entry succesful..${COLOR_END}"

    # Unmount the folder in case the connectin was lost
    sudo umount -l "${OUTPUT}" 2> /dev/null

    # Make sure that output folder is R/O if the network drive disconnects
    mkdir -p "${OUTPUT}"
    chmod -R -w "${OUTPUT}" 2> /dev/null

    echo; echo
    username=
    while [ -z "${username}" ];
    do
        echo -e "${COLOR_YELLOW}Please enter your DTU username (do not include @dtu.biosustain.dk)${COLOR_END}"
        read username

        # sanitize username
        username=$(echo "${username}" | sed -e's#[^a-z0-9\.]##gi')
    done

    echo -e "${COLOR_GREEN}OK! Username is '${username}'..${COLOR_END}"

    echo; echo
    echo -e "${COLOR_YELLOW}Attempting to open network drive; plase enter your DTU password if asked!${COLOR_END}"
    while ! sudo mount "${NETWORK_DRIVE}" "${OUTPUT}" -o user=${username},vers=2.1,noperm;
    do
        echo -e "${COLOR_RED}Failed to open network drive; retrying ..${COLOR_END}"
    done

    echo -e "${COLOR_GREEN}OK! Network drive is connected!${COLOR_END}"
fi


echo; echo
echo -e "${COLOR_GREEN}Starting Bioprofile logging script ..${COLOR_END}"


./venv/bin/python3 bioprofile400.py

echo; echo
echo -e "${COLOR_RED}Logger terminated. Press ENTER to close window.${COLOR_END}"
read