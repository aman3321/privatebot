import nextcord
from nextcord.ext import commands
from nextcord import File, Embed, FFmpegPCMAudio
from nextcord.ext import application_checks
from nextcord.ui import View, Button, TextInput
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

SPOTIFY_CLIENT_ID = "854b5f2974f249e5b2b0d266c849677b"
SPOTIFY_CLIENT_SECRET = "996e39b1abbc4a5bbf3609fd871afcb4"

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

# Define a global lock for synchronization
download_lock = Lock()

async def update_presence():
    await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.playing, name="/help | For Commands"))

def get_spotify_album_art(song_title):
    try:
        # Search for the song on Spotify
        result = sp.search(q=song_title, limit=1, type='track')
        
        # Get the album art URL
        album_art_url = result['tracks']['items'][0]['album']['images'][0]['url']
        return album_art_url
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

song_queue = []
current_song = None  # List to hold queued songs
loop_current = False # Flag to indicate if loop is enabled for the current song
current_video_id = None  # Initialize it as None
voice_client = None  # Initialize voice_client
has_sent_playing_message = False
skip_flag = False


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await update_presence()
    
# Define download folder
download_folder = os.path.join(os.getcwd(), "Music Downloads")

common_download_path = os.path.join(download_folder, f"%(title)s.%(ext)s")  # Common download path

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
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(download_folder, f"%(title)s.%(ext)s"),  # Use the common download path
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

                    scrubbed_title = scrub_song_title(original_title)
                    scrubbed_path = os.path.join(download_folder, f"{scrubbed_title}.mp3")

                    if os.path.exists(scrubbed_path):
                        file = nextcord.File(scrubbed_path, filename=f"{scrubbed_title}.mp3")
                        
                        # Get the album art URL from Spotify
                        album_art_url = get_spotify_album_art(original_title)
                        
                        embed = create_embed('📥 Song Downloaded', original_title)
                        
                        # Set the album art as the thumbnail in the embed (if available)
                        if album_art_url:
                            embed.set_thumbnail(url=album_art_url)
                        
                        await interaction.followup.send(file=file, embed=embed, ephemeral=False)
                    else:
                        embed = create_embed('🚫 No Video Found', 'No video found for the song.')
                        await interaction.followup.send(embed=embed, ephemeral=True)

                    break

            except yt_dlp.DownloadError:
                continue

            except Exception as e:
                print(e)
                embed = create_embed('⚠️ Error', 'An error occurred.')
                await interaction.followup.send(embed=embed, ephemeral=True)

def create_embed(title, description=None, color=None):
    embed = nextcord.Embed(title=title, description=description, color=0x1f8b4c)
    embed.set_author(name=f"🔊📀{config['bot_name']}📀🔊", url=config["bot_url"])
    embed.set_thumbnail(url=config["bot_thumbnail"])
    embed.set_footer(text=config["bot_footer"])
    embed.timestamp = datetime.datetime.utcnow()
    return embed

# Create a semaphore to synchronize asynchronous tasks
download_semaphore = asyncio.Semaphore(1)

song_downloaded = False

async def downloader_task(interaction, loading_message, scrubbed_path, scrubbed_title, voice_channel):
    global song_downloaded  # Declare the global variable

    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(download_folder, f"{scrubbed_title}.%(ext)s"),
            'quiet': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        search_query = f"ytsearch1:{scrubbed_title}"
        ydl = yt_dlp.YoutubeDL(ydl_opts)
        info = await bot.loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=True))
        video_info = info['entries'][0]
        current_video_id = video_info.get('id')
        original_title = video_info.get('title')

        # Process downloaded video information here if needed

        # Mark the song as downloaded
        song_downloaded = True

    except Exception as e:
        print(e)
        await handle_download_error(interaction, loading_message)
        song_downloaded = False  # Mark the song as not downloaded in case of an error

    # Add the song to the queue if it has been successfully downloaded and if audio is already playing
    if song_downloaded and any(vc.channel == voice_channel for vc in bot.voice_clients):
        song_queue.append((scrubbed_path, scrubbed_title))
        embed = create_embed('🎵 Song Added', scrubbed_title)

        # Set the album art as the thumbnail in the embed (if available)
        album_art_url = get_spotify_album_art(scrubbed_title)
        if album_art_url:
            embed.set_thumbnail(url=album_art_url)

        asyncio.create_task(interaction.followup.send(embed=embed, ephemeral=False))

async def handle_download_error(interaction, loading_message):
    await interaction.followup.send('⚠️ An error occurred while downloading the song.', ephemeral=True)
    await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.playing, name='🎵 No song playing 🎵'))
    await loading_message.delete()

async def send_song_added_embed(interaction, song_title):
    embed = create_embed('🎵 Song Added', song_title)

    # Set the album art as the thumbnail in the embed (if available)
    album_art_url = get_spotify_album_art(song_title)
    if album_art_url:
        embed.set_thumbnail(url=album_art_url)

    await interaction.followup.send(embed=embed, ephemeral=False)

async def add_to_queue(interaction, scrubbed_path, scrubbed_title):
    song_queue.append((scrubbed_path, scrubbed_title))  # Append scrubbed title to the queue
    embed = create_embed('🎵 Song Added', scrubbed_title)

    # Set the album art as the thumbnail in the embed (if available)
    album_art_url = get_spotify_album_art(scrubbed_title)
    if album_art_url:
        embed.set_thumbnail(url=album_art_url)

    await interaction.followup.send(embed=embed, ephemeral=False)

# Modify the after_download function to remove the task of adding to queue
def after_download(status, interaction, scrubbed_path, scrubbed_title, voice_channel):
    if status['status'] == 'finished':
        if os.path.exists(scrubbed_path):
            if any(vc.channel == voice_channel for vc in bot.voice_clients):
                # No need to add to queue here
                embed = create_embed('🎵 Song Added', scrubbed_title)

                # Set the album art as the thumbnail in the embed (if available)
                album_art_url = get_spotify_album_art(scrubbed_title)
                if album_art_url:
                    embed.set_thumbnail(url=album_art_url)

                asyncio.create_task(interaction.followup.send(embed=embed, ephemeral=False))
            else:
                asyncio.create_task(connect_to_voice_channel())  # Use connect_to_voice_channel function
                asyncio.create_task(play_song(voice_client, scrubbed_path, scrubbed_title, interaction))  # Use scrubbed title
                if first_play is None:
                    first_play = False  # Initialize `first_play` if it's not defined
        else:
            asyncio.create_task(interaction.followup.send('⚠️ No video found for the song.', ephemeral=True))
     
async def handle_download_error(interaction, loading_message):
    error_embed = create_embed('⚠️ An error occurred', 'An error occurred while downloading the song.')
    await interaction.followup.send(embed=error_embed, ephemeral=True)
    await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.playing, name='🎵 No song playing 🎵'))
    await loading_message.delete()

@bot.slash_command(name='play', description='▶️ Play a song from YouTube')
async def play(interaction: nextcord.Interaction, song_title: str):
    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel

    if not voice_channel:
        await interaction.response.send('🚫 You need to be in a voice channel to use this command.', ephemeral=True)
        return

    scrubbed_title = scrub_song_title(song_title)
    scrubbed_path = os.path.join(download_folder, f"{scrubbed_title}.mp3")  # Define scrubbed_path here

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)

    if not voice_client or not voice_client.is_connected():
        voice_client = await voice_channel.connect()

    print("Scrubbed Path:", scrubbed_path)

    if os.path.exists(scrubbed_path):
        if voice_client.is_playing() or voice_client.is_paused():
            # Check if a download is in progress
            if hasattr(play, 'download_in_progress') and play.download_in_progress:
                # If a download is in progress, add the song to the queue once it's done downloading
                play.download_queue.append((scrubbed_path, scrubbed_title))
                await send_song_added_embed(interaction, scrubbed_title)
            else:
                # If not downloading, start playing the song immediately
                await play_song(voice_client, scrubbed_path, scrubbed_title, interaction)
        else:
            # If not playing or paused, start playing the song immediately
            await play_song(voice_client, scrubbed_path, scrubbed_title, interaction)
    else:
        if not hasattr(play, 'download_in_progress'):
            play.download_in_progress = False
            play.download_queue = []

        if not play.download_in_progress:
            play.download_in_progress = True
            loading_message = await interaction.followup.send('📥 Downloading the song, this might take a while...', ephemeral=True)
            asyncio.create_task(downloader_task(interaction, loading_message, scrubbed_path, scrubbed_title, voice_client))

    if play.download_in_progress:
        # Song is already playing; add it to the download queue
        play.download_queue.append((scrubbed_path, scrubbed_title))
        await send_song_added_embed(interaction, scrubbed_title)

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

    songs = get_playlist(playlist_name)

    if not songs:
        embed = create_embed('🚫 Load Playlist', f"The playlist '{playlist_name}' does not exist.")
        await interaction.response.send(embed=embed)
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

        for song_title in songs:
            # Get the album art URL from Spotify
            album_art_url = get_spotify_album_art(song_title)
            
            embed = create_embed('🎵 Song Added', song_title)
            
            # Set the album art as the thumbnail in the embed (if available)
            if album_art_url:
                embed.set_thumbnail(url=album_art_url)
            
            await interaction.followup.send(embed=embed)

            for proxy in proxy_list:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(download_folder, f"{song_title}.%(ext)s"),  # Use the common download path
                    'quiet': True,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'proxy': proxy,
                }

                song_path = os.path.join(download_path, f"{song_title}.mp3")
                scrubbed_title = scrub_song_title(song_title)
                scrubbed_path = os.path.join(download_path, f"{scrubbed_title}.mp3")

                if not os.path.exists(scrubbed_path):  # If the file doesn't exist, initiate a download task
                    await asyncio.create_task(downloader(song_title, proxy, ydl_opts, song_path, scrubbed_path, interaction, voice_client))

                # Append the scrubbed title to the song_queue
                song_queue.append((scrubbed_path, scrubbed_title))

        if not voice_client.is_playing() and song_queue:
            song_path, song_title = song_queue.pop(0)
            await play_song(voice_client, song_path, song_title, interaction)

    except Exception as e:
        print(e)
 
@bot.slash_command(name='create_playlist', description='🎵 Create a playlist with the current queue 🎵')
async def create_playlist(interaction: nextcord.Interaction, playlist_name: str, 
                        song1: str, song2: str = None, song3: str = None, song4: str = None, 
                        song5: str = None, song6: str = None, song7: str = None, song8: str = None, 
                        song9: str = None, song10: str = None, song11: str = None, song12: str = None, 
                        song13: str = None, song14: str = None, song15: str = None, song16: str = None, 
                        song17: str = None, song18: str = None, song19: str = None, song20: str = None):
    songs = [song for song in [song1, song2, song3, song4, song5, song6, song7, song8, song9, song10, 
                              song11, song12, song13, song14, song15, song16, song17, song18, song19, 
                              song20] if song is not None]

    if not songs:
        embed = nextcord.Embed(title='🎶 Create Playlist 🎶', description='❌ Please provide at least one song title. ❌', color=0x1f8b4c)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Assuming save_playlist is a function that saves the playlist
    save_playlist(playlist_name, songs)

    embed = nextcord.Embed(title='🎶 Create Playlist 🎶', description=f"✅ The playlist '{playlist_name}' has been created and saved. ✅", color=0x1f8b4c)
    await interaction.response.send_message(embed=embed)

@bot.slash_command(name='playlists', description='🎵 Show a list of all saved playlists')
async def playlists(ctx):
    try:
        playlists = get_all_playlists()

        if playlists:
            embed = create_embed('🎵 Saved Playlists', '\n'.join(playlists))
            await ctx.send(embed=embed)
        else:
            embed = create_embed('🚫 Saved Playlists', 'No playlists found.')
            await ctx.send(embed=embed)

    except nextcord.errors.NotFound:
        embed = create_embed('⚠️ Error', 'An error occurred while retrieving the playlists.')
        await ctx.send(embed=embed)

@bot.slash_command(name='deleteplaylist', description='🗑️ Delete a saved playlist')
async def delete_playlist(ctx, playlist_name: str):
    delete_playlist(playlist_name)

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
    # Defer the response
    await interaction.response.defer()

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    song_title = "No song currently playing."

    if voice_client:
        if voice_client.is_playing() or voice_client.is_paused():
            skip_flag = True
            voice_client.stop()
        else:
            await interaction.followup.send("No song is currently playing.", ephemeral=True)
            return

    if song_queue:  # Ensure song_queue is properly defined and accessible
        # Get the next song using indexing
        next_song = song_queue[0]  
        song_path, song_title = next_song

        # Remove the song that was skipped from the queue
        song_queue.pop(0)

        # Get the album art URL from Spotify
        album_art_url = get_spotify_album_art(song_title)
        
        # Define the embed variable for the response message
        embed = create_embed('Song Skipped', f"🎵 Now playing 🎵 | {song_title}")  # Ensure create_embed is defined
        
        # Set the album art as the thumbnail in the embed (if available)
        if album_art_url:
            embed.set_thumbnail(url=album_art_url)

        try:
            await interaction.followup.send(embed=embed)  # Send a follow-up message
        except nextcord.errors.InteractionResponded:
            pass  # Ignore the error if the interaction has already been responded to

        scrubbed_title = scrub_song_title(song_title)  # Ensure this function is defined and working
        scrubbed_path = os.path.join(os.path.dirname(song_path), f"{scrubbed_title}.mp3")

        if os.path.exists(scrubbed_path):
            await play_song(voice_client, scrubbed_path, song_title, interaction)  # Ensure play_song is defined

        await update_presence()  # Ensure update_presence is defined
    else:
        try:
            await interaction.followup.send("No more songs in the queue.", ephemeral=True)  # Corrected here
        except nextcord.errors.InteractionResponded:
            pass  # Ignore the error if the interaction has already been responded to

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

@bot.slash_command(name='volume', description='🔊 Change the volume level of the bot.')
async def volume(interaction: nextcord.Interaction, volume: float):
    if volume < 0 or volume > 1:
        await interaction.response.send_message('Volume must be between 0 and 1.', ephemeral=True)
        return

    voice_client = nextcord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.source:
        voice_client.source.volume = volume
        embed = create_embed('🔊 Volume Changed', f'The volume has been set to {volume}.')
        await interaction.response.send_message(embed=embed, ephemeral=False)
    else:
        embed = create_embed('🔊 Volume Change', 'No song is currently playing.')
        await interaction.response.send_message(embed=embed, ephemeral=False)

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
    songs = get_playlist(album_name)

    if not songs:
        embed = nextcord.Embed(title='🎶 Show Playlist 🎶', description=f"❌ The playlist '{album_name}' does not exist. ❌", color=0xFF0000)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = nextcord.Embed(title=f"🎶 Playlist: {album_name} 🎶", description='🎵 Songs in the playlist: 🎵', color=0x1f8b4c)

    for index, song_title in enumerate(songs, start=1):
        embed.add_field(name=f'🎵 Song {index}', value=song_title, inline=False)

    await interaction.response.send_message(embed=embed)

@bot.slash_command(name='loop', description='🔁 Enable the loop feature for the currently playing song')
async def loop_song(interaction: nextcord.Interaction):
    global loop_current

    if loop_current:
        embed = create_embed('🔁 Loop', 'Loop feature is already enabled.', color=0x1f8b4c)
    else:
        loop_current = True
        embed = create_embed('🔁 Loop', 'Loop feature has been enabled for the currently playing song.', color=0x1f8b4c)

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

    embed = create_embed('🔀 Shuffle Queue', 'The song queue has been shuffled.', color=0x1f8b4c)
    await interaction.response.send_message(embed=embed, ephemeral=False)

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

    if song_queue:  # Ensure song_queue is properly defined and accessible
        # Get the next song using indexing
        next_song = song_queue[0]  
        song_path, song_title = next_song
        scrubbed_title = scrub_song_title(song_title)  # Ensure this function is defined and working
        scrubbed_path = os.path.join(os.path.dirname(song_path), f"{scrubbed_title}.mp3")

        # Remove the song that was skipped from the queue
        song_queue.pop(0)

        # Get the album art URL from Spotify
        album_art_url = get_spotify_album_art(song_title)
        
        # Define the embed variable for the response message
        embed = create_embed('Song Skipped', f"🎵Now playing🎵: {song_title}")  # Ensure create_embed is defined
        
        # Set the album art as the thumbnail in the embed (if available)
        if album_art_url:
            embed.set_thumbnail(url=album_art_url)

        # Reset the has_sent_playing_message flag to ensure the next song sends a "Now Playing" message
        has_sent_playing_message = False

        if os.path.exists(scrubbed_path):
            await play_song(voice_client, scrubbed_path, song_title)  # Ensure play_song is defined

        await update_presence()  # Ensure update_presence is defined
    else:
        # If there are no more songs in the queue, send a message indicating this
        print("No more songs in the queue.")

def create_playlist_table():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS playlists
                      (name TEXT PRIMARY KEY, songs TEXT)''')

    conn.commit()
    conn.close()

def save_playlist(playlist_name, songs):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute('INSERT OR REPLACE INTO playlists (name, songs) VALUES (?, ?)', (playlist_name, ','.join(songs)))

    conn.commit()
    conn.close()


def delete_playlist(playlist_name):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute('DELETE FROM playlists WHERE name = ?', (playlist_name,))

    conn.commit()
    conn.close()

def get_all_playlists():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute('SELECT name FROM playlists')
    playlists = cursor.fetchall()

    conn.close()

    return [playlist[0] for playlist in playlists]

def get_playlist(playlist_name):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute('SELECT songs FROM playlists WHERE name = ?', (playlist_name,))
    result = cursor.fetchone()

    conn.close()

    return result[0].split(',') if result else []
  
create_playlist_table()

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

    return song_title

async def play_song(voice_client, song_path, song_title, interaction=None, stream_title=None):
    global first_play
    global loop_current
    global has_sent_playing_message

    try:
        source = nextcord.FFmpegPCMAudio(str(song_path))

        async def after_play(error):
            nonlocal song_path, song_title
            if error:
                print(f"Error playing song: {error}")

            if loop_current and not error:
                new_source = nextcord.FFmpegPCMAudio(str(song_path))
                voice_client.play(nextcord.PCMVolumeTransformer(new_source), after=after_play)
            else:
                await play_next_song(voice_client, song_title)

        voice_client.play(nextcord.PCMVolumeTransformer(source), after=after_play)

        if not has_sent_playing_message and interaction:
            # Get the album art URL from Spotify
            album_art_url = get_spotify_album_art(song_title)
            
            embed = create_embed('🎵Now Playing🎵', song_title)
            
            # Set the album art as the thumbnail in the embed (if available)
            if album_art_url:
                embed.set_thumbnail(url=album_art_url)
            
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

        if not song_queue:
            await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.playing, name='🎵 No song playing 🎵'))
        else:
            next_song = song_queue.pop(0)
            song_path, song_title = next_song
            await play_song(voice_client, song_path, song_title, stream_title=stream_title)

async def downloader(song_title, proxy, ydl_opts, song_path, scrubbed_path, interaction, voice_client, voice_channel, song_queue):
    try:
        async with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch1:{song_title}"
            print(f"Using proxy: {proxy} for search: {search_query}")
            info = await ydl.extract_info(search_query, download=True)
            video = info['entries'][0]
            original_title = video.get('title')
            current_video_id = video.get('id')

            os.rename(song_path, scrubbed_path)
    except Exception as e:
        print(e)
        embed = create_embed('⚠️ Error', 'An error occurred while processing the playlist.')
        await interaction.followup.send(embed=embed)
        return

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
