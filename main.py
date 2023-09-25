import nextcord
from nextcord.ext import commands
from nextcord import File, Embed, FFmpegPCMAudio
from nextcord.ext import application_checks
from nextcord.ui import View, button, TextInput
from bs4 import BeautifulSoup
import random
import yt_dlp
import glob
import aiohttp
import datetime
import sqlite3
import asyncio
import os
import requests
import unicodedata
import shutil
import subprocess
import platform
import re
import json
import lyricsgenius
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from asyncio import Lock

with open('config.json', 'r') as file:
    config = json.load(file)

SPOTIFY_CLIENT_ID = config["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = config["SPOTIFY_CLIENT_SECRET"]

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

# Define a global lock for synchronization
download_lock = Lock()

async def update_presence():
    await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.playing, name="/help | For Commands"))

def preprocess_title(title):
    # Use regular expressions to remove text within parentheses and square brackets
    title = re.sub(r'\([^)]*\)', '', title)  # Remove text within parentheses
    title = re.sub(r'\[[^\]]*\]', '', title)  # Remove text within square brackets
    # Remove extra spaces
    title = ' '.join(title.split())
    return title

def get_spotify_album_art(song_title, artist_name=None):
    try:
        # Preprocess the song title to remove text within parentheses and square brackets
        song_title = preprocess_title(song_title)

        # Formulate the search query
        if artist_name:
            query = f'track:{song_title} artist:{artist_name}'
        else:
            query = f'track:{song_title}'

        # Search for the song on Spotify
        result = sp.search(q=query, limit=1, type='track')
        
        # Check if any results were returned
        if result['tracks']['items']:
            # Get the track and album data
            track_data = result['tracks']['items'][0]
            album_data = track_data['album']
            
            # Get the album art URL
            album_art_url = album_data['images'][0]['url'] if album_data['images'] else None

            return {"album_art_url": album_art_url, "album_data": album_data, "track_data": track_data}
        else:
            print(f"No results found for query: {query}")
            return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None
        
# Load configuration from JSON file
with open('config.json', 'r') as config_file:
    config = json.load(config_file)
    genius_api_key = config['genius_api_key']

genius = lyricsgenius.Genius(genius_api_key)

def load_proxies(file_path):
    with open(file_path, "r") as file:
        proxies = [line.strip() for line in file if line.strip()]
    return proxies

proxy_list = load_proxies("proxies.txt")  # Replace with the path to your proxies.txt file

def set_console_title(title):
    if platform.system() == "Windows":
        subprocess.call(["title", title], shell=True)
    else:
        subprocess.call(["printf", "\033]0;%s\007" % title], shell=True)

def fetch_album_songs(album_name):
    try:
        # Search for the album
        result = sp.search(q=f'album:{album_name}', type='album')
        if not result['albums']['items']:
            return None
        
        album = result['albums']['items'][0]  # Get the first album found

        # Get the artist name from the album details
        artist_name = album['artists'][0]['name']

        # Get the album's tracks
        tracks = sp.album_tracks(album['id'])
        song_details = [(track['name'], artist_name) for track in tracks['items']]  # Store songs as tuples with song name and artist name
        return song_details
    except IndexError:
        # No album found
        return None
    except Exception as e:
        print(e)
        return None


# Call this function before launching your bot
set_console_title("ARCADE MUSIC BOT CONSOLE - MADE BY POTSMOKINGPIKA")

first_play = True
saved_queues = {}
db_file = 'playlist.db'

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix=' ', intents=intents)

# Add this at the beginning of your script where you define other global variables
is_downloading = False
song_queue = []
current_song = None  # List to hold queued songs
loop_current = False # Flag to indicate if loop is enabled for the current song
current_video_id = None  # Initialize it as None
voice_client = None  # Initialize voice_client
has_sent_playing_message = False
global skip_flag
skip_flag = False
current_song_position = 0
is_downloading = False
currently_playing = False

@bot.event
async def on_voice_state_update(member, before, after):
    global current_song_position
    global current_song

    if member.id == bot.user.id and before.channel is not None and after.channel is None:
        # The bot was in a channel before and is not in any channel now, i.e., it got disconnected
        # Save the current song position
        if bot.voice_clients[0].is_playing():
            current_song_position = bot.voice_clients[0].source.position
        # Try to reconnect
        voice_client = await before.channel.connect()
        
        # Resume playing the song from the saved position
        if current_song:
            voice_client.play(discord.FFmpegPCMAudio(current_song), after=lambda e: print('Player error: %s' % e) if e else None)
            voice_client.source = discord.PCMVolumeTransformer(voice_client.source)
            voice_client.source.volume = 0.5
            voice_client.seek(current_song_position)

def custom_print(message):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f'''
\033[1;31m  _____  _____ _     _ _______ _______ _     _ __   _ _______ _______\033[0m
\033[1;32m |_____]   |   |____/  |_____|    |    |     | | \  | |______ |______\033[0m
\033[1;34m |       __|__ |    \_ |     |    |    |_____| |  \_| |______ ______|\033[0m
\033[1;35m                                                                     \033[0m
    ''')
    print(f'\033[1;36mLogged in as {bot.user.name}\033[0m')
    print(message)

@bot.event
async def on_ready():
    global bot_name
    bot_name = bot.user.name
    custom_print(" ")

    # Set the bot's presence
    await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.listening, name="/help | For Commands"))
    
# Define download folder
download_folder = os.path.join(os.getcwd(), "Music Downloads")

common_download_path = os.path.join(download_folder, f"%(title)s.%(ext)s")  # Common download path

@bot.slash_command(name='loadyoutubelist', description='Load and play songs from a YouTube playlist')
async def load_youtube_list(interaction: nextcord.Interaction, playlist_url: str):
    await interaction.response.defer()
    
    # Set the download folder to the "Music Downloads" folder in the cwd
    download_folder = os.path.join(os.getcwd(), 'Music Downloads')
    
    # Ensure the download folder exists
    os.makedirs(download_folder, exist_ok=True)
    
    # Define a regular expression pattern to match content between brackets and pipe characters
    pattern = re.compile(r'\[.*?\]|\(.*?\)|\|')
    
    # Define the title of the blacklisted video
    blacklisted_title = "Pokemon Battle Music Mix 【1 Hour】"
    
    try:
        # Extract playlist information using yt_dlp
        with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'force_generic_extractor': True}) as ydl:
            result = ydl.extract_info(playlist_url, download=False)
            if 'entries' not in result:
                await interaction.followup.send('Could not retrieve playlist entries.', ephemeral=True)
                return
            
            # Loop through each entry in the playlist
            for entry in result['entries']:
                video_url = entry['url']
                original_title = entry['title']
                
                # Check if the video title matches the blacklisted title
                if original_title == blacklisted_title:
                    print(f"Skipped blacklisted video: {original_title}")
                    continue  # Skip this video and continue with the next one
                
                # Remove content between brackets and pipe characters
                song_title = pattern.sub('', original_title).strip()
                
                # Scrub the song title
                scrubbed_title = scrub_song_title(song_title)
                
                # Create the path for the song file in the queue using the scrubbed title without adding the .mp3 extension
                download_path = os.path.join(download_folder, f"{scrubbed_title}")
                
                # Check if the file already exists with the .mp3 extension
                if not os.path.exists(download_path + ".mp3"):
                    # Download the song if it doesn't exist
                    for proxy in proxy_list:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': download_path + ".%(ext)s", # Add the .mp3 extension here
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'proxy': proxy,
                            'quiet': True,
                        }
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([video_url])
                        
                        # Break the loop if the song is downloaded successfully
                        if os.path.exists(download_path + ".mp3"):
                            break
                
                # Add the song to the song_queue using the modified filename with the .mp3 extension
                song_queue.append((download_path + ".mp3", song_title))
                
                # Create embed with song info
                embed = create_embed('🎵 Song Added 🎵', song_title)
                await interaction.followup.send(embed=embed, ephemeral=False)
        
        # Start playing the songs from the song_queue
        if song_queue:
            voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
            
            # Check if the bot is connected to a voice channel
            if voice_client:
                if not voice_client.is_playing() and not voice_client.is_paused():
                    song_path, song_title = song_queue.pop(0)
                    await play_song(voice_client, song_path, song_title, interaction)
                else:
                    await interaction.followup.send('Bot is already playing music.', ephemeral=True)
            else:
                # If the bot is not connected to any voice channel, connect to the user's voice channel and start playing
                voice_channel = interaction.user.voice.channel
                if voice_channel:
                    voice_client = await voice_channel.connect()
                    song_path, song_title = song_queue.pop(0)
                    await play_song(voice_client, song_path, song_title, interaction)
                else:
                    await interaction.followup.send('You need to be in a voice channel to use this command.', ephemeral=True)
        else:
            await interaction.followup.send('No songs were added to the queue.', ephemeral=True)
    
    except Exception as e:
        print(e)
        await interaction.followup.send('An error occurred while loading the YouTube playlist.', ephemeral=True)

        
@bot.slash_command(name='whatsplaying', description='Show the currently playing audio file and its Spotify data')
async def whats_playing(interaction: nextcord.Interaction):
    # Check if a song is currently playing
    if current_song:
        song_title_with_artist = current_song  # Get the title and artist of the currently playing song
        
        # Get the album art URL and other details from Spotify
        spotify_data = get_spotify_album_art(song_title_with_artist)
        album_art_url = spotify_data["album_art_url"] if spotify_data else None
        album_data = spotify_data["album_data"] if spotify_data else None
        
        # Define the embed variable for the response message
        embed = create_embed('🎵 Now Playing 🎵', f"{song_title_with_artist}")
        
        # Set the album art as the thumbnail in the embed (if available)
        if album_art_url:
            embed.set_thumbnail(url=album_art_url)
        
        # Add more album data to the embed (if available)
        if album_data:
            album_name = album_data.get('name', 'Unknown Album')
            artist_name = album_data['artists'][0].get('name', 'Unknown Artist') if album_data['artists'] else 'Unknown Artist'
            release_date = album_data.get('release_date', 'Unknown Release Date')
            embed.add_field(name='Album', value=album_name, inline=True)
            embed.add_field(name='Artist', value=artist_name, inline=True)
            embed.add_field(name='Release Date', value=release_date, inline=True)
        
        # Send the embed as a response
        await interaction.response.send_message(embed=embed)
    else:
        # Send a response indicating that no song is currently playing
        await interaction.response.send_message("No song is currently playing.", ephemeral=True)

@bot.slash_command(name='loadalbum', description='🎵 Load and play a saved album')
async def load_album(interaction: nextcord.Interaction, album_name: str, artist_name: str = None):
    global first_play
    global is_downloading  # Declare the global variable to track the downloading status

    # Load Spotify API credentials from config.json
    with open('config.json', 'r') as file:
        config = json.load(file)

    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=config["SPOTIPY_CLIENT_ID"], client_secret=config["SPOTIPY_CLIENT_SECRET"]))

    # Create an instance of the PlaylistDatabase class
    db = PlaylistDatabase()

    # Check if the album is already in the database
    existing_album_songs = db.get_playlist(album_name)
    
    if existing_album_songs:
        # If the album is already in the database, load it from there
        songs = existing_album_songs
    else:
        # If the album is not in the database, fetch the songs from Spotify
        search_query = f"album:{album_name}"
        if artist_name:
            search_query += f" artist:{artist_name}"
        result = sp.search(q=search_query, type="album")

        # Get the album's track details
        if result['albums']['items']:
            album = result['albums']['items'][0]
            album_artist_name = album['artists'][0]['name']  # Get the artist's name

            # If artist_name parameter is used, ensure the found album matches the artist name
            if artist_name and artist_name.lower() != album_artist_name.lower():
                embed = create_embed('🚫 Load Album', f"No album found with the name '{album_name}' by '{artist_name}'.")
                await interaction.response.send_message(embed=embed)
                db.close()  # Close the database connection when done
                return

            album_id = album['id']
            tracks = sp.album_tracks(album_id)
            songs = [(track['name'], album_artist_name) for track in tracks['items']]  # Store songs as tuples with song name and artist name
            
            # Save the new album to the database with artist name included
            db.save_playlist(f"{album_name} - {album_artist_name}", songs)  # Save the song and artist name tuples to the database
        else:
            embed = create_embed('🚫 Load Album', f"No album found with the name '{album_name}'.")
            await interaction.response.send_message(embed=embed)
            db.close()  # Close the database connection when done
            return

    voice_channel = interaction.user.voice.channel

    if not voice_channel:
        embed = create_embed('🚫 Load Album', 'You need to be in a voice channel to use this command.')
        await interaction.response.send_message(embed=embed)
        return

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if not voice_client:
        voice_client = await voice_channel.connect()

    try:
        await interaction.response.defer()

        cwd = os.getcwd()
        download_path = os.path.join(cwd, 'Music Downloads')

        for song_title, artist_name in songs:
            # Get the exact song title and artist name from Spotify
            spotify_data = get_spotify_album_art(song_title, artist_name)
            if spotify_data:
                song_title = spotify_data["track_data"]["name"]  # Update song title with Spotify data
                artist_name = spotify_data["track_data"]["artists"][0]["name"]  # Update artist name with Spotify data
                album_art_url = spotify_data["album_art_url"]  # Get the album art URL
                album_data = spotify_data["album_data"]  # Get the album data
            else:
                album_art_url = None  # Set to None if no data is returned from Spotify
                album_data = None

            embed = create_embed('🎵 Song Added 🎵', song_title)
            
            # Set the album art as the thumbnail in the embed (if available)
            if album_art_url:
                embed.set_thumbnail(url=album_art_url)
            
            # Add more album data to the embed (if available)
            if album_data:
                album_name = album_data.get('name', 'Unknown Album')
                release_date = album_data.get('release_date', 'Unknown Release Date')
                embed.add_field(name='Album', value=album_name, inline=True)
                embed.add_field(name='Artist', value=artist_name, inline=True)
                embed.add_field(name='Release Date', value=release_date, inline=True)
            
            await interaction.followup.send(embed=embed)

            # Define the scrubbed path outside the proxy loop to avoid duplicate entries in the queue
            scrubbed_title = scrub_song_title(f"{song_title} - {artist_name}")  # Include artist name in the scrubbed title
            scrubbed_path = os.path.join(download_path, f"{scrubbed_title}.mp3")
            
            if not os.path.exists(scrubbed_path):  # If the file doesn't exist, initiate a download task
                if is_downloading:
                    await interaction.followup.send(f'A song is currently downloading. Please try again later.', ephemeral=True)
                    return
                
                for proxy in proxy_list:
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': os.path.join(download_folder, f"{scrub_song_title(song_title)} - {scrub_song_title(artist_name)}.%(ext)s"),  # Include artist name in the file name
                        'quiet': True,
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'proxy': proxy,
                    }

                    song_path = os.path.join(download_path, f"{scrub_song_title(song_title)} - {scrub_song_title(artist_name)}.mp3")  # Include artist name in the file path
                    scrubbed_title = scrub_song_title(f"{song_title} - {artist_name}")  # Include artist name in the scrubbed title
                    scrubbed_path = os.path.join(download_path, f"{scrubbed_title}.mp3")
                    await asyncio.create_task(downloader(f"{song_title} - {artist_name}", proxy, ydl_opts, song_path, scrubbed_path, interaction, voice_client, voice_channel, song_queue))
            
            # Check if the song is already in the queue before adding it
            if not any(scrubbed_path in song_info for song_info in song_queue):
                song_queue.append((scrubbed_path, scrubbed_title))

        # Start playing after all songs have been added to the queue
        if first_play and not voice_client.is_playing() and song_queue:
            first_play = False
            song_path, song_title = song_queue.pop(0)
            await play_song(voice_client, song_path, song_title, interaction)
        elif not voice_client.is_playing() and song_queue:
            song_path, song_title = song_queue.pop(0)
            await play_song(voice_client, song_path, song_title, interaction)

    except Exception as e:
        print(e)
    finally:
        db.close()  # Close the database connection when done

@bot.slash_command(name='tunein', description='Play audio from a YouTube stream in the voice channel')
async def tunein(interaction: nextcord.Interaction, url: str):
    await interaction.response.defer()
    
    # Get the voice channel the user is in
    voice_channel = interaction.user.voice.channel
    if not voice_channel:
        await interaction.followup.send('You need to be in a voice channel to use this command.', ephemeral=True)
        return

    # Get the voice client
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if not voice_client:
        voice_client = await voice_channel.connect()

    # Use yt_dlp to get the audio stream URL
    ydl_opts = {
        'format': 'bestaudio',
        'quiet': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        audio_url = info['formats'][0]['url']
        video_title = info.get('title', 'Unknown title')
        video_thumbnail = info.get('thumbnail', '')

    # Create an audio source from the audio stream URL
    audio_source = nextcord.FFmpegPCMAudio(audio_url)

    # Play the audio in the voice channel
    voice_client.play(nextcord.PCMVolumeTransformer(audio_source), after=lambda e: print('Player error: %s' % e) if e else None)
    
    
    # Create an embed message with the video details
    embed = create_embed(
        title='🎵 Now Playing 🎵',
        description=f'[**{video_title}**]({url})',
        color=0x00ff00
    )
    if video_thumbnail:
        embed.set_image(url=video_thumbnail)

    await interaction.followup.send(embed=embed, ephemeral=False)

@bot.slash_command(name='tuneout', description='Stop playing the YouTube stream and reset the bot presence')
async def tuneout(interaction: nextcord.Interaction):
    await interaction.response.defer()
    
    # Get the voice client
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    
    if not voice_client or not voice_client.is_playing():
        embed = create_embed('🔴 Stream Stopped 🔴', 'I am not playing any streams right now.')
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Stop playing the audio stream
    voice_client.stop()
    
    # Disconnect from the voice channel
    await voice_client.disconnect()
    
    embed = create_embed('🔴 Stream Stopped 🔴', 'I am not playing any streams right now.')
    await interaction.followup.send(embed=embed, ephemeral=False)

@bot.slash_command(name='lyrics', description='🎤 Get the lyrics of a song')
async def lyrics_command(interaction: nextcord.Interaction, song_name: str):
    await interaction.response.defer()

    try:
        # Get the track details from Spotify using Spotipy
        track_details = get_spotify_track_details(song_name)

        if not track_details:
            await interaction.followup.send('🚫 Could not find track details on Spotify.', ephemeral=True)
            return

        # Get the track name and artist name from the track details
        track_name = track_details['name']
        artist_name = track_details['artists'][0]['name']

        # Get the album art URL from the track details
        album_art_url = track_details['album']['images'][0]['url']

        # Search for the song lyrics using the Genius API
        song = genius.search_song(track_name, artist_name)

        if song:
            # Fetch the lyrics from the Genius API
            song_lyrics = song.lyrics

            # Remove unwanted content
            song_lyrics = song_lyrics.split("You might also like")[0]

            # Split the lyrics into chunks of 2048 characters or less
            lyrics_chunks = [song_lyrics[i:i + 2048] for i in range(0, len(song_lyrics), 2048)]

            for chunk in lyrics_chunks:
                # Create an embed for each chunk of lyrics
                embed = create_embed(f"🎵 Lyrics for {song.title}", "")
                
                # Set the album art as the thumbnail in the embed
                embed.set_thumbnail(url=album_art_url)

                # Split the chunk into parts of 1024 characters or less
                chunk_parts = [chunk[i:i + 1024] for i in range(0, len(chunk), 1024)]

                for part in chunk_parts:
                    # Add each part as a field in the embed
                    embed.add_field(name="‎", value=part, inline=False)  # Using a zero-width space as the field name

                # Send the embed
                await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send('🚫 Lyrics not found for the song.')

    except Exception as e:
        print(e)
        await interaction.followup.send('⚠️ An error occurred.', ephemeral=True)

# Function to get track details from Spotify using Spotipy
def get_spotify_track_details(song_name):
    # Initialize the Spotipy client with your Spotify API credentials
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id="YOUR_SPOTIFY_CLIENT_ID", client_secret="YOUR_SPOTIFY_CLIENT_SECRET"))

    # Search for the track on Spotify
    result = sp.search(q=song_name, type='track', limit=1)

    # Get the track details from the search results
    if result['tracks']['items']:
        return result['tracks']['items'][0]
    else:
        return None

@bot.slash_command(name='download', description='📥 Download a song from YouTube')
async def download_song(interaction: nextcord.Interaction, song_title: str):
    await interaction.response.defer()

    # Use the download_lock to ensure only one download task runs at a time
    async with download_lock:
        for proxy in proxy_list:
            scrubbed_title = scrub_song_title(song_title)
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(download_folder, f"{scrubbed_title}.%(ext)s"),  # Save the file with the search term used
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'proxy': proxy,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    search_query = f"ytsearch1:{song_title}"
                    print(f"Using proxy: {proxy} for search: {search_query}")
                    info = ydl.extract_info(search_query, download=True)
                    video = info['entries'][0]
                    original_title = video.get('title')

                    scrubbed_path = os.path.join(download_folder, f"{scrubbed_title}.mp3")

                    if os.path.exists(scrubbed_path):
                        file = nextcord.File(scrubbed_path, filename=f"{scrubbed_title}.mp3")
                        
                        # Get the album art URL and album data from Spotify
                        spotify_data = get_spotify_album_art(original_title)
                        album_art_url = spotify_data["album_art_url"] if spotify_data else None
                        album_data = spotify_data["album_data"] if spotify_data else None
                        
                        embed = create_embed('📥 Song Downloaded', original_title)
                        
                        # Set the album art as the thumbnail in the embed (if available)
                        if album_art_url:
                            embed.set_thumbnail(url=album_art_url)
                        
                        # Add more album data to the embed (if available)
                        if album_data:
                            album_name = album_data.get('name', 'Unknown Album')
                            artist_name = album_data['artists'][0].get('name', 'Unknown Artist') if album_data['artists'] else 'Unknown Artist'
                            release_date = album_data.get('release_date', 'Unknown Release Date')
                            embed.add_field(name='Album', value=album_name, inline=True)
                            embed.add_field(name='Artist', value=artist_name, inline=True)
                            embed.add_field(name='Release Date', value=release_date, inline=True)
                        
                        await interaction.followup.send(file=file, embed=embed, ephemeral=False)
                    else:
                        embed = create_embed('🚫 No Video Found', 'No video found for the song.')
                        await interaction.followup.send(embed=embed, ephemeral=True)

                    break

            except yt_dlp.DownloadError:
                continue

            except Exception as e:
                print(e)
                embed = create_embed('⚠️ Error ⚠️', 'An error occurred.')
                await interaction.followup.send(embed=embed, ephemeral=True)



def create_embed(title, description=None, color=None):
    embed = nextcord.Embed(title=title, description=description, color=0xf1c40f)
    embed.set_author(name=f"🔊📀{config['bot_name']}📀🔊", url=config["bot_url"])
    embed.set_thumbnail(url=config["bot_thumbnail"])
    embed.set_footer(text=config["bot_footer"])
    embed.timestamp = datetime.datetime.utcnow()
    return embed

async def check_download_status(interaction):
    global is_downloading
    if is_downloading:
        embed = create_embed('⚠️ Download in Progress', 'Another song is currently being downloaded. Please try again in a few moments.')
        await interaction.followup.send(embed=embed, ephemeral=True)
        return True
    return False

download_semaphore = asyncio.Semaphore(1)

@bot.slash_command(name='play', description='▶️ Play a song from YouTube')
async def play(interaction: nextcord.Interaction, video_url: str):
    global current_video_id
    global first_play
    await interaction.response.defer()

    voice_channel = interaction.user.voice.channel
    if not voice_channel:
        await interaction.response.send('🚫 You need to be in a voice channel to use this command.', ephemeral=True)
        return

    # Extract video ID from the URL
    video_id = video_url.split("v=")[1]

    # Define a regular expression pattern to match content between brackets and pipe characters
    pattern = re.compile(r'\[.*?\]|\(.*?\)|\|')

    # Define the title of the blacklisted video
    blacklisted_title = "Pokemon Battle Music Mix 【1 Hour】"

    # Use yt_dlp to get video information
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        video_info = ydl.extract_info(video_id, download=False)
        original_title = video_info.get('title')
        artist_name = video_info.get('uploader')

    # Check if the original title matches the blacklisted title
    if original_title == blacklisted_title:
        await interaction.followup.send('⚠️ This song is blacklisted and cannot be played.', ephemeral=True)
        return

    # Remove content between brackets and pipe characters
    song_title = pattern.sub('', original_title).strip()

    scrubbed_title = scrub_song_title(song_title)
    artist_name_scrubbed = scrub_song_title(artist_name) if artist_name else 'Unknown Artist'

    # Create the path for the song file using the scrubbed title
    download_path = os.path.join(download_folder, f"{scrubbed_title}")

    # Check if the file already exists with the .mp3 extension
    if not os.path.exists(download_path + ".mp3"):
        # Download the song if it doesn't exist
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': download_path + ".%(ext)s",  # Add the .mp3 extension here
            'quiet': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
                current_video_id = video_id
        except Exception as e:
            print(e)
            await interaction.followup.send('⚠️ An error occurred while downloading the song.', ephemeral=True)
            return

    # Add the song to the song_queue using the modified filename with the .mp3 extension
    song_queue.append((download_path + ".mp3", song_title))

    # Create embed with song info
    embed = create_embed('🎵 Song Added 🎵', song_title)
    await interaction.followup.send(embed=embed, ephemeral=False)

    # Connect to the voice channel and start playing the song
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client:
        if not voice_client.is_playing() and not voice_client.is_paused():
            song_path, song_title = song_queue.pop(0)
            await play_song(voice_client, song_path, song_title, interaction)
    else:
        voice_client = await voice_channel.connect()
        song_path, song_title = song_queue.pop(0)
        await play_song(voice_client, song_path, song_title, interaction)


                    
@bot.slash_command(name='radio', description='📻 Play songs from the "Music Downloads" folder')
async def radio(interaction: nextcord.Interaction):
    voice_channel = interaction.user.voice.channel

    if not voice_channel:
        embed = create_embed('📻 Radio', 'You need to be in a voice channel to use this command.')
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if not voice_client:  # If the bot is not connected to any voice channel, connect it
        voice_client = await voice_channel.connect()

    await interaction.response.defer()  # Acknowledge the interaction

    songs_folder = os.path.join(os.getcwd(), 'Music Downloads')
    songs = glob.glob(os.path.join(songs_folder, '*.mp3'))

    if not songs:
        embed = create_embed('📻 Radio', 'No songs found in the "Music Downloads" folder.')
        await interaction.followup.send_message(embed=embed, ephemeral=True)
        return

    # Clear the existing queue
    song_queue.clear()

    for song_path in songs:
        song_title = os.path.splitext(os.path.basename(song_path))[0]
        song_queue.append((song_path, song_title))

    # Shuffle the song queue to play songs in a random order
    random.shuffle(song_queue)

    if not voice_client.is_playing():
        await play_song(voice_client, song_queue[0][0], song_queue[0][1], interaction)

    embed = create_embed('📻 Radio', 'Songs added to the queue.')
    await interaction.followup.send_message(embed=embed, ephemeral=False)

@bot.slash_command(name='saveplaylist', description='💾 Save the current song queue with a custom name')
async def save_queue(interaction: nextcord.Interaction, playlist_name: str):
    global song_queue

    if not song_queue:
        await interaction.response.send_message('No songs in the queue to save.', ephemeral=True)
        return

    songs = [song[1] for song in song_queue]

    save_playlist(playlist_name, songs)

    embed = create_embed('💾 Save Playlist', f"The current song queue has been saved as '{playlist_name}'.")
    await interaction.response.send_message(embed=embed, ephemeral=False)
        
@bot.slash_command(name='loadplaylist', description='🎵 Load and play a saved playlist')
async def load_queue(interaction: nextcord.Interaction, playlist_name: str):
    global first_play
    global is_downloading  # Declare the global variable to track the downloading status

    db = PlaylistDatabase()  # Create an instance of the PlaylistDatabase class
    songs = db.get_playlist(playlist_name)  # Use the method of the PlaylistDatabase class

    if not songs:
        embed = create_embed('🚫 Load Playlist', f"The playlist '{playlist_name}' does not exist.")
        await interaction.response.send_message(embed=embed)  # Updated this line
        return

    voice_channel = interaction.user.voice.channel

    if not voice_channel:
        embed = create_embed('🚫 Load Playlist', 'You need to be in a voice channel to use this command.')
        await interaction.response.send(embed=embed)
        return

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if not voice_client:
        voice_client = await voice_channel.connect()

    try:
        await interaction.response.defer()

        cwd = os.getcwd()
        download_path = os.path.join(cwd, 'Music Downloads')

        if first_play and not voice_client.is_playing() and song_queue:
            first_play = False
            song_path, song_title = song_queue.pop(0)
            await play_song(voice_client, song_path, song_title, interaction)

        for song_title, artist_name in songs:
            # Get the exact song title and artist name from Spotify
            spotify_data = get_spotify_album_art(song_title, artist_name)
            if spotify_data:
                song_title = spotify_data["track_data"]["name"]  # Update song title with Spotify data
                artist_name = spotify_data["track_data"]["artists"][0]["name"]  # Update artist name with Spotify data
                album_art_url = spotify_data["album_art_url"]  # Get the album art URL
                album_data = spotify_data["album_data"]  # Get the album data
            else:
                album_art_url = None  # Set to None if no data is returned from Spotify
                album_data = None

            embed = create_embed('🎵 Song Added 🎵', song_title)
            
            # Set the album art as the thumbnail in the embed (if available)
            if album_art_url:
                embed.set_thumbnail(url=album_art_url)
            
            # Add more album data to the embed (if available)
            if album_data:
                album_name = album_data.get('name', 'Unknown Album')
                release_date = album_data.get('release_date', 'Unknown Release Date')
                embed.add_field(name='Album', value=album_name, inline=True)
                embed.add_field(name='Artist', value=artist_name, inline=True)
                embed.add_field(name='Release Date', value=release_date, inline=True)
            
            await interaction.followup.send(embed=embed)

            for proxy in proxy_list:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(download_folder, f"{scrub_song_title(song_title)} - {scrub_song_title(artist_name)}.%(ext)s"),  # Include artist name in the file name
                    'quiet': True,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'proxy': proxy,
                }

                song_path = os.path.join(download_path, f"{scrub_song_title(song_title)} - {scrub_song_title(artist_name)}.mp3")  # Include artist name in the file path
                scrubbed_title = scrub_song_title(f"{song_title} - {artist_name}")  # Include artist name in the scrubbed title
                scrubbed_path = os.path.join(download_path, f"{scrubbed_title}.mp3")

                if not os.path.exists(scrubbed_path):  # If the file doesn't exist, initiate a download task
                    if is_downloading:
                        await interaction.followup.send(f'A song is currently downloading. Please try again later.', ephemeral=True)
                        return
                    await asyncio.create_task(downloader(f"{song_title} - {artist_name}", proxy, ydl_opts, song_path, scrubbed_path, interaction, voice_client, voice_channel, song_queue))  # Include artist name in the search query

                # Append the scrubbed title to the song_queue
                song_queue.append((scrubbed_path, scrubbed_title))

        if not voice_client.is_playing() and song_queue:
            song_path, song_title = song_queue.pop(0)
            await play_song(voice_client, song_path, song_title, interaction)

    except Exception as e:
        print(e)
    finally:
        db.close()  # Close the database connection when done

@bot.slash_command(name='create_playlist', description='🎵 Create a playlist with the current queue 🎵')
async def create_playlist(
        interaction: nextcord.Interaction, 
        playlist_name: str = nextcord.SlashOption(description="The name of your new playlist"), 
        song1: str = nextcord.SlashOption(description="The first song in the playlist"),
        song2: str = nextcord.SlashOption(description="The second song in the playlist", required=False),
        song3: str = nextcord.SlashOption(description="The third song in the playlist", required=False),
        song4: str = nextcord.SlashOption(description="The fourth song in the playlist", required=False),
        song5: str = nextcord.SlashOption(description="The fifth song in the playlist", required=False),
        song6: str = nextcord.SlashOption(description="The sixth song in the playlist", required=False),
        song7: str = nextcord.SlashOption(description="The seventh song in the playlist", required=False),
        song8: str = nextcord.SlashOption(description="The eighth song in the playlist", required=False),
        song9: str = nextcord.SlashOption(description="The ninth song in the playlist", required=False),
        song10: str = nextcord.SlashOption(description="The tenth song in the playlist", required=False),
        song11: str = nextcord.SlashOption(description="The eleventh song in the playlist", required=False),
        song12: str = nextcord.SlashOption(description="The twelfth song in the playlist", required=False),
        song13: str = nextcord.SlashOption(description="The thirteenth song in the playlist", required=False),
        song14: str = nextcord.SlashOption(description="The fourteenth song in the playlist", required=False),
        song15: str = nextcord.SlashOption(description="The fifteenth song in the playlist", required=False),
        song16: str = nextcord.SlashOption(description="The sixteenth song in the playlist", required=False),
        song17: str = nextcord.SlashOption(description="The seventeenth song in the playlist", required=False),
        song18: str = nextcord.SlashOption(description="The eighteenth song in the playlist", required=False),
        song19: str = nextcord.SlashOption(description="The nineteenth song in the playlist", required=False),
        song20: str = nextcord.SlashOption(description="The twentieth song in the playlist", required=False),
    ):
    db = PlaylistDatabase()
    songs = [song for song in [song1, song2, song3, song4, song5, song6, song7, song8, song9, song10, 
                              song11, song12, song13, song14, song15, song16, song17, song18, song19, 
                              song20] if song is not None]

    if not songs:
        embed = nextcord.Embed(title='🎶 Create Playlist 🎶', description='❌ Please provide at least one song title. ❌', color=0xf1c40f)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    db.save_playlist(playlist_name, songs)
    db.close()

    embed = nextcord.Embed(title='🎶 Create Playlist 🎶', description=f"✅ The playlist '{playlist_name}' has been created and saved. ✅", color=0xf1c40f)
    await interaction.response.send_message(embed=embed)



@bot.slash_command(name='playlists', description='🎵 Show a list of all saved playlists')
async def playlists(ctx):
    db = PlaylistDatabase()
    try:
        playlists = db.get_all_playlists()
        db.close()

        if playlists:
            embed = create_embed('🎵 Saved Playlists 🎵', '\n'.join(playlists))
            await ctx.send(embed=embed)
        else:
            embed = create_embed('🚫 Saved Playlists 🚫', 'No playlists found.')
            await ctx.send(embed=embed)

    except nextcord.errors.NotFound:
        db.close()
        embed = create_embed('⚠️ Error ⚠️', 'An error occurred while retrieving the playlists.')
        await ctx.send(embed=embed)

@bot.slash_command(name='deleteplaylist', description='🗑️ Delete a saved playlist')
async def delete_playlist(ctx, playlist_name: str):
    db = PlaylistDatabase()
    db.delete_playlist(playlist_name)
    db.close()

    embed = create_embed('🗑️ Delete Playlist', f"The playlist '{playlist_name}' has been deleted.")
    await ctx.send(embed=embed)


@bot.slash_command(name='songlist', description='🎵 Show the list of songs in the queue 🎵')
async def songlist(interaction: nextcord.Interaction):
    embed_title = '🎶 Song Queue 🎶'
    
    if song_queue:
        embed = create_embed(embed_title, '')

        if len(song_queue) <= 25:  # Check if the number of songs can fit in a single embed
            for index, song in enumerate(song_queue, start=1):
                song_url, song_title = song
                embed.add_field(name=f'🎵 Song {index}', value=song_title, inline=False)
        else:
            embed_limit = 24  # Limit the number of fields in the embed to leave space for the "More Songs" field
            for index, song in enumerate(song_queue[:embed_limit], start=1):
                song_url, song_title = song
                embed.add_field(name=f'🎵 Song {index}', value=song_title, inline=False)
            remaining_songs = len(song_queue) - embed_limit
            embed.add_field(name='🔽 More Songs 🔽', value=f'{remaining_songs} more songs in the queue', inline=False)
            last_song_index = len(song_queue)  # Get the index of the last song in the queue
            embed.set_footer(text=f"🎧 Last song displayed: Song {last_song_index}")

        await interaction.send(embed=embed)
    else:
        embed = create_embed(embed_title, '❌ No songs in the queue ❌')
        await interaction.send(embed=embed)

@bot.slash_command(name='next', description='Go to the next song in the queue')
async def next_song(interaction: nextcord.Interaction):
    global skip_flag
    await interaction.response.defer()

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)

    if not voice_client or not (voice_client.is_playing() or voice_client.is_paused()):
        await interaction.followup.send("No song is currently playing.", ephemeral=True)
        return

    skip_flag = True
    voice_client.stop()

    # Check if there are more songs in the queue
    if not song_queue:
        await interaction.followup.send("No more songs in the queue.", ephemeral=True)
        return

    next_song_path, next_song_title_with_artist = song_queue.pop(0)

    # Get the album art URL and other details from Spotify, if the function is available
    if 'get_spotify_album_art' in globals():
        spotify_data = get_spotify_album_art(next_song_title_with_artist)
        album_art_url = spotify_data.get("album_art_url")
        album_data = spotify_data.get("album_data")
    else:
        album_art_url = None
        album_data = None

    # Define the embed variable for the response message
    embed = create_embed('🎵 Next Song 🎵', next_song_title_with_artist)

    # Set the album art as the thumbnail in the embed (if available)
    if album_art_url:
        embed.set_thumbnail(url=album_art_url)

    # Add more album data to the embed (if available)
    if album_data:
        album_name = album_data.get('name', 'Unknown Album')
        artist_name = ", ".join([artist["name"] for artist in album_data["artists"]]) if album_data.get('artists') else 'Unknown Artist'
        release_date = album_data.get('release_date', 'Unknown Release Date')
        embed.add_field(name='Album', value=album_name, inline=True)
        embed.add_field(name='Artist', value=artist_name, inline=True)
        embed.add_field(name='Release Date', value=release_date, inline=True)

    await interaction.followup.send(embed=embed)
    await play_song(voice_client, next_song_path, next_song_title_with_artist, interaction)

@bot.slash_command(name='pause', description='⏸️ Pause the current song')
async def pause_song(interaction: nextcord.Interaction):
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        embed = create_embed('⏸️ Pause', 'The current song has been paused.')
        await interaction.response.send_message(embed=embed, ephemeral=False)
    else:
        embed = create_embed('⏸️ Pause', 'No song is currently playing.')
        await interaction.response.send_message(embed=embed, ephemeral=False)


class VolumeView(View):
    def __init__(self, voice_client):
        super().__init__()
        self.voice_client = voice_client

    @button(label='Volume Up', style=nextcord.ButtonStyle.green)
    async def volume_up(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        global is_downloading
        if is_downloading:
            await interaction.response.send_message('Cannot change volume while a song is downloading.', ephemeral=True)
            return

        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = min(self.voice_client.source.volume + 0.1, 1.0)
            await interaction.response.defer()

    @button(label='Volume Down', style=nextcord.ButtonStyle.red)
    async def volume_down(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        global is_downloading
        if is_downloading:
            await interaction.response.send_message('Cannot change volume while a song is downloading.', ephemeral=True)
            return

        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = max(self.voice_client.source.volume - 0.1, 0.0)
            await interaction.response.defer()

@bot.slash_command(name='volume', description='🔊 Change the volume level of the bot.')
async def volume(interaction: nextcord.Interaction):
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    
    if voice_client and voice_client.source:
        view = VolumeView(voice_client)
        await interaction.response.send_message('Use the buttons to adjust the volume.', view=view, ephemeral=False)
    else:
        await interaction.response.send_message('No song is currently playing.', ephemeral=False)

@bot.slash_command(name='resume', description='▶️ Resume the current song')
async def resume_song(interaction: nextcord.Interaction):
    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        embed = create_embed('▶️ Resume', 'The current song has been resumed.')
        await interaction.response.send_message(embed=embed, ephemeral=False)
    else:
        embed = create_embed('▶️ Resume', 'No song is currently paused.')
        await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.slash_command(name='clear', description='🗑️ Clear the current queue of all songs')
async def clear_queue(interaction: nextcord.Interaction):
    global song_queue

    if song_queue:
        song_queue.clear()
        embed = create_embed('🗑️ Clear Queue', 'The song queue has been cleared.')
        await interaction.response.send_message(embed=embed, ephemeral=False)
    else:
        embed = create_embed('🗑️ Clear Queue', 'No songs in the queue to clear.')
        await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.slash_command(name='showplaylist', description='🎵 Show all songs in a playlist 🎵')
async def show_playlist(interaction: nextcord.Interaction, album_name: str):
    # Create an instance of the PlaylistDatabase class
    db = PlaylistDatabase()
    
    # Get the list of songs in the specified playlist
    songs = db.get_playlist(album_name)

    # Close the database connection
    db.close()

    if not songs:
        embed = nextcord.Embed(title='🎶 Show Playlist 🎶', description=f"❌ The playlist '{album_name}' does not exist. ❌", color=0xFF0000)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = nextcord.Embed(title=f"🎶 Playlist: {album_name} 🎶", description='🎵 Songs in the playlist: 🎵', color=0xf1c40f)

    for index, song_title in enumerate(songs, start=1):
        embed.add_field(name=f'🎵 Song {index}', value=song_title, inline=False)

    await interaction.response.send_message(embed=embed)


@bot.slash_command(name='loop', description='🔁 Enable the loop feature for the currently playing song')
async def loop_song(interaction: nextcord.Interaction):
    global loop_current

    if loop_current:
        embed = create_embed('🔁 Loop', 'Loop feature is already enabled.', color=0xf1c40f)
    else:
        loop_current = True
        loop_current = True
        embed = create_embed('🔁 Loop', 'Loop feature has been enabled for the currently playing song.', color=0xf1c40f)

    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.slash_command(name='stoploop', description='⏹️ Disable the loop feature')
async def stop_loop(interaction: nextcord.Interaction):
    global loop_current

    if loop_current:
        loop_current = False
        embed = create_embed('⏹️ Stop Loop', 'Loop feature has been disabled.', color=0xFF0000)
    else:
        embed = create_embed('⏹️ Stop Loop', 'Loop feature is already disabled.', color=0xFF0000)

    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.slash_command(name='shuffle', description='🔀 Shuffle the current song queue')
async def shuffle_queue(interaction: nextcord.Interaction):
    global song_queue  # Ensure to define song_queue as global

    if not song_queue:
        embed = create_embed('🔀 Shuffle Queue', 'The song queue is empty.', color=0xFF0000)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    random.shuffle(song_queue)

    embed = create_embed('🔀 Shuffle Queue', 'The song queue has been shuffled.', color=0xf1c40f)
    await interaction.response.send_message(embed=embed, ephemeral=False)

# Your Discord user ID
YOUR_USER_ID = 820062277842632744

@bot.slash_command(name='feedback', description='Send feedback to the bot owner')
async def feedback(interaction: nextcord.Interaction, user_feedback: str = nextcord.SlashOption(description="Your feedback", required=True)):
    # Fetch the User object for your account
    owner = bot.get_user(YOUR_USER_ID)
    
    if owner:
        # Send the feedback as a Direct Message
        await owner.send(f"Feedback from {interaction.user.display_name}#{interaction.user.discriminator} ({interaction.user.id}): {user_feedback}")
        await interaction.response.send_message("Thank you for your feedback!")
    else:
        await interaction.response.send_message("Failed to send feedback. Please try again later.")

@bot.slash_command(name='help', description='Show a list of available commands')
async def help_command(ctx):
    embed = create_embed('🤖 Bot Commands 🤖', 'Here is a list of available commands:')

    # Playback Commands
    embed.add_field(name='🎵 Playback Commands 🎵', value='Commands to control music playback.', inline=False)
    embed.add_field(name='/play [Song Name - Artist Name]', value='🎶 Play a song from YouTube.', inline=True)
    embed.add_field(name='/pause', value='⏸ Pause the current playing song.', inline=True)
    embed.add_field(name='/resume', value='▶ Resume the song from where you paused.', inline=True)
    embed.add_field(name='/next', value='⏭ Skip the current song.', inline=True)
    embed.add_field(name='/volume [0.0-1.0]', value='🔊 Control the bot\'s output volume.', inline=True)
    
    # Stream Commands
    embed.add_field(name='🎥 Stream Commands 🎥', value='Commands to control YouTube stream playback.', inline=False)
    embed.add_field(name='/tunein [YouTube URL]', value='🎵 Play audio from a YouTube stream in the voice channel.', inline=True)
    embed.add_field(name='/tuneout', value='🛑 Stop the YouTube stream and reset the bot\'s presence.', inline=True)

    # Playlist Commands
    embed.add_field(name='🎵 Playlist Commands 🎵', value='Commands to manage playlists.', inline=False)
    embed.add_field(name='/createplaylist [Playlist Name] [song1]-[song10]', value='📝 Create a custom playlist (max 10 songs per playlist).', inline=True)
    embed.add_field(name='/saveplaylist [Playlist Name]', value='💾 Save the current song list as a playlist.', inline=True)
    embed.add_field(name='/loadplaylist [Playlist Name]', value='📂 Load a saved playlist.', inline=True)
    embed.add_field(name='/showplaylist [Playlist Name]', value='👀 View all songs in a saved playlist.', inline=True)
    embed.add_field(name='/deleteplaylist [Playlist Name]', value='🗑 Delete a saved playlist.', inline=True)

    # Queue Commands
    embed.add_field(name='🎵 Queue Commands 🎵', value='Commands to manage the song queue.', inline=False)
    embed.add_field(name='/songlist', value='📜 View all songs ready to play (excluding the current song).', inline=True)
    embed.add_field(name='/clear', value='🧹 Clear all songs in the queue.', inline=True)
    embed.add_field(name='/shuffle', value='🔀 Shuffle all songs in the queue.', inline=True)

    # Loop Commands
    embed.add_field(name='🎵 Loop Commands 🎵', value='Commands to loop songs.', inline=False)
    embed.add_field(name='/loop', value='🔁 Loop the current song.', inline=True)
    embed.add_field(name='/stoploop', value='🛑 Stop looping the current song.', inline=True)

    # Extra Commands
    embed.add_field(name='🎵 Extra Commands 🎵', value='Additional commands for extra functionalities.', inline=False)
    embed.add_field(name='/download', value='💾 Download the current song and share it in the Discord chat.', inline=True)
    embed.add_field(name='/radio', value='📻 Load all previously downloaded songs into the queue.', inline=True)

    await ctx.send(embed=embed)

async def play_next_song(voice_client, song_title):
    global current_song
    global skip_flag
    global has_sent_playing_message

    if voice_client.is_playing() or skip_flag:
        skip_flag = False
        return

    if song_queue:
        next_song = song_queue[0]  
        song_path, song_title = next_song
        scrubbed_title = scrub_song_title(song_title)
        scrubbed_path = os.path.join(os.path.dirname(song_path), f"{scrubbed_title}.mp3")

        song_queue.pop(0)

        spotify_data = get_spotify_album_art(song_title)
        if spotify_data:
            album_art_url = spotify_data["album_art_url"]
            album_data = spotify_data["album_data"]
            track_data = spotify_data["track_data"]

            song_title = track_data["name"]
            artist_name = ", ".join([artist["name"] for artist in track_data["artists"]])
            album_name = album_data.get('name', 'Unknown Album')
            release_date = album_data.get('release_date', 'Unknown Release Date')

            embed = create_embed('🎵 Now Playing 🎵', song_title)
            
            if album_art_url:
                embed.set_thumbnail(url=album_art_url)
            
            embed.add_field(name='Artist', value=artist_name, inline=True)
            embed.add_field(name='Album', value=album_name, inline=True)
            embed.add_field(name='Release Date', value=release_date, inline=True)
        else:
            embed = create_embed('🎵 Now Playing 🎵', song_title)

        has_sent_playing_message = False

        if os.path.exists(scrubbed_path):
            await play_song(voice_client, scrubbed_path, song_title)
    else:
        print("No more songs in the queue.")


class PlaylistDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(os.path.join(os.getcwd(), 'playlist.db'))
        self.cursor = self.conn.cursor()
        self.create_playlist_table()

    def create_playlist_table(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS playlists
                              (name TEXT PRIMARY KEY, songs TEXT)''')
        self.conn.commit()

    def save_playlist(self, playlist_name, songs):
        songs_json = json.dumps(songs)
        self.cursor.execute('INSERT OR REPLACE INTO playlists (name, songs) VALUES (?, ?)', (playlist_name, songs_json))
        self.conn.commit()

    def delete_playlist(self, playlist_name):
        self.cursor.execute('DELETE FROM playlists WHERE name = ?', (playlist_name,))
        self.conn.commit()

    def get_all_playlists(self):
        self.cursor.execute('SELECT name FROM playlists')
        playlists = self.cursor.fetchall()
        return [playlist[0] for playlist in playlists]

    def get_playlist(self, playlist_name):
        self.cursor.execute('SELECT songs FROM playlists WHERE name = ?', (playlist_name,))
        result = self.cursor.fetchone()
        return json.loads(result[0]) if result else []

    def close(self):
        self.conn.close()

def get_playlist(album_name):
    try:
        # Connect to your database
        conn = sqlite3.connect('playlist.db')
        
        # Create a cursor to interact with your database
        cursor = conn.cursor()
        
        # Write a query to fetch all songs from the specified playlist
        cursor.execute("SELECT song_title FROM playlists WHERE album_name = ?", (album_name,))
        
        # Fetch all results from the executed query
        songs = cursor.fetchall()
        
        # Close the database connection
        conn.close()
        
        # Return the list of song titles; using a list comprehension to get titles from tuples
        return [song[0] for song in songs]
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def remove_emojis(text):
    emoji_pattern = re.compile("["
                               u"\U0001F600-\U0001F64F"  # emoticons
                               u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                               u"\U0001F680-\U0001F6FF"  # transport & map symbols
                               u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                               "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def scrub_song_title(song_title):
    # Remove emojis from the title
    song_title = remove_emojis(song_title)

    # Remove invalid characters from the title
    song_title = re.sub(r'[<>:"/\\|?*]', '', song_title)

    # Normalize the title to remove special characters
    song_title = unicodedata.normalize('NFKC', song_title)

    # Remove all characters that are not letters, numbers, or whitespace
    song_title = re.sub(r'[^\w\s]', '', song_title)

    return song_title
    
async def play_song(voice_client, song_path, song_title, interaction=None, stream_title=None):
    global first_play
    global loop_current
    global has_sent_playing_message
    global current_song  # Declare current_song as a global variable
    global currently_playing  # Declare currently_playing as a global variable
    
    # Update the current_song variable with the title of the song that is about to play
    current_song = song_title
    
    try:
        source = nextcord.FFmpegPCMAudio(str(song_path))

        async def after_play(error):
            nonlocal song_path, song_title
            global currently_playing  # Declare currently_playing as a global variable
            
            # Reset currently_playing flag at the beginning of the callback
            currently_playing = False
            
            if error:
                print(f"Error playing song: {error}")

            if loop_current and not error:
                new_source = nextcord.FFmpegPCMAudio(str(song_path))
                voice_client.play(nextcord.PCMVolumeTransformer(new_source), after=after_play)
                currently_playing = True  # Set currently_playing to True as a song is playing
            else:
                print("Calling play_next_song...")  # Debugging print statement
                await play_next_song(voice_client, song_title)

        # Check if a song is already playing
        if currently_playing:
            print("Already playing audio.")
            return

        voice_client.play(nextcord.PCMVolumeTransformer(source), after=after_play)
        currently_playing = True  # Set currently_playing to True as a song is playing

        if not has_sent_playing_message and interaction:
            # Get the album art URL from Spotify
            spotify_data = get_spotify_album_art(song_title)
            album_art_url = spotify_data["album_art_url"] if spotify_data else None
            album_data = spotify_data["album_data"] if spotify_data else None

            embed = create_embed('🎵 Now Playing 🎵', song_title)
            
            # Set the album art as the thumbnail in the embed (if available)
            if album_art_url:
                embed.set_thumbnail(url=album_art_url)
            
            # Add more album data to the embed (if available)
            if album_data:
                album_name = album_data.get('name', 'Unknown Album')
                artist_name = album_data['artists'][0].get('name', 'Unknown Artist') if album_data['artists'] else 'Unknown Artist'
                release_date = album_data.get('release_date', 'Unknown Release Date')
                embed.add_field(name='Album', value=album_name, inline=True)
                embed.add_field(name='Artist', value=artist_name, inline=True)
                embed.add_field(name='Release Date', value=release_date, inline=True)

            await interaction.followup.send(content=' ', embed=embed, ephemeral=False)
            has_sent_playing_message = True

        while voice_client.is_playing() or voice_client.is_paused():
            await asyncio.sleep(1)

        if not song_queue:
            await asyncio.sleep(25)
            if not song_queue:
                await voice_client.disconnect()

    except nextcord.errors.NotFound:
        pass
    except Exception as e:
        print(e)

        if song_queue:
            next_song = song_queue.pop(0)
            next_song_path, next_song_title = next_song
            await play_song(voice_client, next_song_path, next_song_title)


async def downloader(song_title, proxy, ydl_opts, song_path, scrubbed_path, interaction, voice_client, voice_channel, song_queue):
    global is_downloading
    try:
        is_downloading = True
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch1:{song_title}"
            print(f"Using proxy: {proxy} for search: {search_query}")
            info = ydl.extract_info(search_query, download=True)  # This is a synchronous call
            video = info['entries'][0]
            original_title = video.get('title')
            current_video_id = video.get('id')

            os.rename(song_path, scrubbed_path)
    except Exception as e:
        print(e)
        embed = create_embed('⚠️ Error ⚠️', 'An error occurred while processing the playlist.')
        await interaction.followup.send(embed=embed)
    finally:
        is_downloading = False

    if os.path.exists(scrubbed_path):
        if any(vc.channel == voice_channel for vc in bot.voice_clients):
            song_queue.append((scrubbed_path, song_title))
        else:
            voice_client = await voice_channel.connect()
            if first_play:
                first_play = False
                await play_song(voice_client, scrubbed_path, song_title, interaction)
            else:
                song_queue.append((scrubbed_path, song_title))

@bot.event
async def on_voice_state_update(member, before, after):
    global first_play
    global voice_client
    global has_sent_playing_message

    if member == bot.user and after.channel is None:
        await bot.change_presence(activity=None)
        first_play = True
        voice_client = None
        has_sent_playing_message = False

bot.run(config["bot_token"])
