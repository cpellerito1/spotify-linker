import json
import requests
import sqlite3
import time
import urllib.parse
import selenium.common.exceptions
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from getpass import getpass


"""
This program "links" songs together on spotify. "links" means that when the first song is playing, it will always add
the second song to queue so it will always play after the first song. This solves the problem of 
you hearing the interlude for a song and want to play its corresponding song right after but can't edit your 
queue. It uses the spotify api to grab info about the currently playing song. It then adds the info about the songs the
user wishes to link to a dictionary and a database for persistent storage. Then as long as this program is running, and
spotify is open, it should always add the second song to the queue when the first one starts playing even if you are on
your phone or a different device.

Setup:
This program is pretty simple but does require selenium, the selenium chrome webdriver and chrome to work. Once you
download the webdriver, you can copy and paste the path to it inside the quotes where it says 'path goes here'
You can also save your username and password in the code if you don't want to enter them every time this program starts

To check for updated versions visit this link: https://github.com/cpellerito1/spotify-linker
"""

# Spotify api info
SPOTIFY_GET_CURRENT_TRACK_URL = 'https://api.spotify.com/v1/me/player/currently-playing'
SPOTIFY_ADD_TO_QUEUE = 'https://api.spotify.com/v1/me/player/queue'
SPOTIFY_GET_DEVICE_ID = 'https://api.spotify.com/v1/me/player/devices'
SPOTIFY_GET_AUTHORIZATION = 'https://accounts.spotify.com/authorize'
REDIRECT_URI = 'http://localhost:8080/authorization'
CLIENT_ID = '82c2f1c0d1d749b78298583797349933'
SCOPE = 'user-read-currently-playing user-read-playback-state user-modify-playback-state'
# Global access token and timer for next token
SPOTIFY_ACCESS_TOKEN = ''
TOKEN_TIME_SET = time.time()
# Global variables to hold username and password while program is running
USERNAME = ''  # TODO: You can save your username inside the quotes here
PASSWORD = ''  # TODO: You can save your password inside the quotes here
# Selenium driver setup
options = Options()
options.add_argument('headless')
options.add_argument('window-size=1920,1080')
# TODO: This path needs to be set to the path where your chrome driver is
driver = webdriver.Chrome("path goes here", options=options)


def get_authentication():
    # Create the request url
    url = SPOTIFY_GET_AUTHORIZATION
    url += "?response_type=token"
    url += "&client_id=" + urllib.parse.quote(CLIENT_ID)
    url += "&scope=" + urllib.parse.quote(SCOPE)
    url += "&redirect_uri=" + urllib.parse.quote(REDIRECT_URI)

    # These variables can be hard coded for convenience
    global USERNAME, PASSWORD
    if USERNAME == '':
        USERNAME = input("Please enter your spotify username: ")
    if PASSWORD == '':
        PASSWORD = getpass("Please enter your spotify password: ")

    # Wait message for user
    print("Authenticating...")

    try:
        driver.get(url)
        driver.find_element(By.ID, 'login-username').send_keys(USERNAME)
        time.sleep(1)
        driver.find_element(By.ID, 'login-password').send_keys(PASSWORD)
        time.sleep(1)
        driver.find_element(By.ID, 'login-button').click()
        time.sleep(2)
    except selenium.common.exceptions.NoSuchElementException:
        pass
    except selenium.common.exceptions.WebDriverException:
        pass

    global TOKEN_TIME_SET
    TOKEN_TIME_SET = time.time()
    time.sleep(10)
    # Get the response url from the browser
    response_url = driver.current_url

    global SPOTIFY_ACCESS_TOKEN
    # Splice the access token off the response url and set the spotify access token
    SPOTIFY_ACCESS_TOKEN = response_url[response_url.find("access") + 13:response_url.rfind('&token_type')]


def get_current_track(access_token):
    response = requests.get(
        SPOTIFY_GET_CURRENT_TRACK_URL,
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )
    # Make sure a song is currently playing
    try:
        response = response.json()
        time_remaining = (response['item']['duration_ms'] - response['progress_ms']) / 1000
        song = {
            "name": response['item']['name'],
            "artist": ', '.join([a['name'] for a in response['item']['artists']]),
            "uri": response['item']['uri'].replace(":", "%3A"),
            "id": response['item']['id'],
            "time_remaining": time_remaining
        }
        return song
    except json.JSONDecodeError:
        print("Error: unable to detect current song, please make sure one is playing")
        time.sleep(10)
        # Create song with error code 1
        return {"id": "Error 1"}
    except KeyError:
        # This means the response returned an error
        error = response['error']['status']
        if error == 503 or error == 502:
            print("Spotify service error, retrying again soon...")
            time.sleep(30)
            # Return an error song so the outer loop can continue running
            return {"id": "Error 50X"}
        elif error == 404:
            print("Error: " + response['error']['message'])
            print("Make sure spotify is open on a device")
            return {"id": "Error 404"}
        elif error == 401:
            get_authentication()
            return {"id": "Error 401"}


def add_song_to_queue(access_token, device_id, song):
    track_uri = SPOTIFY_ADD_TO_QUEUE + "?uri=" + song['linked']['uri'] + "&device_id=" + device_id

    response = requests.post(
        track_uri,
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    )
    # Check the response for errors
    try:
        response = response.json()
        print("Error: " + response['error']['message'])
    except json.JSONDecodeError:
        print("Success! " + song['linked']['name'] + " added to queue")


# This function gets the device id of the currently active device
def get_device_id(access_token):
    response = requests.get(
        SPOTIFY_GET_DEVICE_ID,
        headers={
            "Authorization": f"Bearer {access_token}"
        }
    ).json()

    try:
        # Get the active devices id
        devices = response['devices']
        for i in devices:
            if i['is_active']:
                return i['id']
        # If it makes it here no devices were active
        print("Error: unable to detect active device, please make sure spotify is open on one of your devices")
        time.sleep(10)
    except KeyError:
        error = response['error']['status']
        if error == 401:
            # This isn't a great way of handling it because of the possibility of infinite recursion
            get_authentication()
            return get_device_id(SPOTIFY_ACCESS_TOKEN)
        elif error == 429:
            print("Rate limit exceeded, please wait...")
            time.sleep(20)
            # Again not a fan of the possibility of infinite recursion
            return get_device_id(access_token)
        else:
            # If there is an error, and it isn't a 401 or 429, print the message and exit
            print("Error:" + response['error']['message'])
            exit(-1)


def get_data_base():
    conn = sqlite3.connect('spotify_linker.db')
    print("Database opened successfully!")
    # Check if the links table already exists and if not add it
    tables = conn.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="links"').fetchall()
    if not tables:
        conn.execute(
            'CREATE TABLE links('
            'Song_ID TEXT PRIMARY KEY NOT NULL,'
            'Song_Name TEXT NOT NULL,'
            'Song_URI TEXT NOT NULL,'
            'Song_Artist TEXT NOT NULL,'
            'Linked_ID TEXT NOT NULL,'
            'Linked_URI TEXT NOT NULL,'
            'Linked_Name TEXT NOT NULL,'
            'Linked_Artist TEXT NOT NULL)'
        )

    return conn


def get_links(data_base):
    table = data_base.execute('SELECT * FROM links')
    # Dictionary to hold the links from the database (if any exist)
    links = {}
    for row in table:
        links[row[0]] = {
            "name": row[1],
            "artist": row[3],
            "linked": {
                "name": row[6],
                "artist": row[7],
                "id": row[4],
                "uri": row[5]
            }
        }

    return links


def print_instructions():
    print("About:")
    print("This program allows you to link songs together so that when the first one plays, the second one is added"
          " to the queue. Unfortunately, due to the spotify api not having support for queue manipulation,\nthis"
          " program can only add the second song to the back of your queue so it works best if your queue is empty.")
    print("How to use:")
    print("The program will prompt you if you wish to add any new 'links' if you wish to do so you would type 'y' and"
          " then the program will walk you through how to do it.")
    print("Bonus:")
    print("This program will ask you for your username and password one time everytime it is ran, however, you can get"
          " around this by adding your username and password in the code.")
    print("Just open this file in any text editor(like notepad, not microsoft word) and edit the USERNAME and PASSWORD")
    print("lines at the top of the file that are labeled with 'TODO:' Then save the file and your login info should be"
          " saved until you change one of them.")


def get_valid_input(prompt):
    ans = input(prompt).lower()
    while ans != 'y' and ans != 'n':
        ans = input("Error: please enter a valid response (y/n): ").lower()
    return ans


def main():
    # Fetch the database if it exists, if not create it and the table links (found in get_data_base())
    data_base = get_data_base()
    # Dictionary to hold the links from the database (if any exist)
    links = get_links(data_base)

    # Ask user if they want to view the instructions
    instructions = get_valid_input("Welcome!\nWould you like to view the instructions?(y/n): ")
    if instructions == 'y':
        print_instructions()

    # Get authentication code
    get_authentication()

    # Set new variable depending on if user wants to add any new connections
    new = get_valid_input("Do you wish to add any new links?(y/n): ")
    # Loop to get the users input, have them use the currently playing song to link
    while new == 'y':
        input("When you are playing the song you want to start the link with press enter")
        song1 = get_current_track(SPOTIFY_ACCESS_TOKEN)
        input("Now, start playing the song you want to link to the first, when it is playing press enter")
        song2 = get_current_track(SPOTIFY_ACCESS_TOKEN)
        # Check if the song is an error
        if song1['id'][:5] == "Error" or song2['id'][:5] == "Error":
            print("Sorry, the link could not be completed, please try again")
            continue
        # Add link to database
        query = "INSERT INTO links(Song_ID, Song_Name, Song_URI, Song_Artist, Linked_ID, Linked_URI, Linked_Name, " \
                "Linked_Artist) VALUES('" + song1['id'] + "', '" + song1['name'] + "', '" + song1['uri'] + "', '" + \
                song1['artist'] + "', '" + song2['id'] + "', '" + song2['uri'] + "', '" + song2['name'] + "', '" + \
                song2['artist'] + "')"
        data_base.execute(query)
        data_base.commit()

        new = get_valid_input("Do you wish to add another link?(y/n): ")
        if new == 'n':
            # Re get the links after new ones were added
            links = get_links(data_base)

    # Print the links if the user wants to
    p_links = get_valid_input("Do you wish to view your active links?(y/n): ")
    if p_links == 'y':
        for song in links:
            print(links[song]['name'] + " by " + links[song]['artist'] + " linked to " + links[song]['linked']['name'] +
                  " by " + links[song]['linked']['artist'])

    # Run continuous loop for checking current song
    while True:
        # Check if the token should be reset
        global TOKEN_TIME_SET
        if time.time() - TOKEN_TIME_SET >= 3480:
            get_authentication()
            TOKEN_TIME_SET = time.time()

        # Get the current track
        current_track = get_current_track(SPOTIFY_ACCESS_TOKEN)
        # Check if the current song is in links
        if links.get(current_track['id']):
            add_song_to_queue(SPOTIFY_ACCESS_TOKEN, get_device_id(SPOTIFY_ACCESS_TOKEN), links[current_track['id']])
            # Check if the access token will expire before the current song ends and refresh it needed
            if (time.time() + current_track['time_remaining']) - TOKEN_TIME_SET >= 3600:
                get_authentication()
            # Wait until the song ends or is skipped to continue
            while current_track['id'] == get_current_track(SPOTIFY_ACCESS_TOKEN)['id']:
                time.sleep(10)


main()

if __name__ == '--spotifylinker--':
    main()
