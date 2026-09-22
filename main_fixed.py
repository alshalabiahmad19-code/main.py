```python
import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord.ext import commands
import yt_dlp


# =========================================================
# Render Health Check
# =========================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Discord music bot is running!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()


# =========================================================
# Discord
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# OWNER VOICE ROOM
# =========================================================

OWNER_VOICE_CHANNEL_ID = 1548094091798257806

song_queues = {}


# =========================================================
# YouTube / yt-dlp
# =========================================================

YTDL_OPTIONS = {
    "format": "bestaudio[ext=webm]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5 "
        "-reconnect_at_eof 1"
    ),
    "options": "-vn"
}


ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


# =========================================================
# YouTube Audio Source
# =========================================================

class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown")

    @classmethod
    async def from_url(cls, query):

        loop = asyncio.get_running_loop()

        def extract():

            data = ytdl.extract_info(
                query,
                download=False
            )

            if not data:
                raise RuntimeError(
                    "yt-dlp لم يرجع أي بيانات."
                )

            if "entries" in data:

                entries = [
                    entry
                    for entry in data["entries"]
                    if entry
                ]

                if not entries:
                    raise RuntimeError(
                        "لم يتم العثور على الأغنية."
                    )

                data = entries[0]

            return data

        data = await loop.run_in_executor(
            None,
            extract
        )

        stream_url = data.get("url")

        if not stream_url:
            raise RuntimeError(
                "لم يتم الحصول على رابط الصوت."
            )

        ffmpeg_path = os.getenv(
            "FFMPEG_PATH",
            "ffmpeg"
        )

        source = discord.FFmpegPCMAudio(
            stream_url,
            executable=ffmpeg_path,
            **FFMPEG_OPTIONS
        )

        return cls(
            source,
            data=data
        )


# =========================================================
# Voice Channel
# =========================================================

def get_owner_channel(guild):

    channel = guild.get_channel(
        OWNER_VOICE_CHANNEL_ID
    )

    if isinstance(channel, discord.VoiceChannel):
        return channel

    return None


async def connect_owner_channel(
    guild,
    message=None
):

    channel = get_owner_channel(guild)

    if channel is None:

        if message:
            await message.channel.send(
                "❌ ما لقيت روم الأونرات. "
                f"تأكد أن ID هو `{OWNER_VOICE_CHANNEL_ID}`."
            )

        return None

    voice = guild.voice_client

    try:

        if voice and voice.is_connected():

            if voice.channel.id != channel.id:
                await voice.move_to(channel)

            return voice

        return await channel.connect(
            reconnect=True
        )

    except discord.Forbidden:

        if message:
            await message.channel.send(
                "❌ البوت ما عنده صلاحية "
                "**Connect** أو **Speak** في روم الأونرات."
            )

    except Exception as e:

        print(
            f"[VOICE ERROR] "
            f"{type(e).__name__}: {e}"
        )

        if message:
            await message.channel.send(
                "❌ فشل دخول روم الأونرات.\n"
                f"`{type(e).__name__}: {e}`"
            )

    return None


def user_in_owner_channel(message):

    if not message.author.voice:
        return False

    if not message.author.voice.channel:
        return False

    owner_channel = get_owner_channel(
        message.guild
    )

    if owner_channel is None:
        return False

    return (
        message.author.voice.channel.id
        == owner_channel.id
    )


# =========================================================
# Queue
# =========================================================

def get_queue(guild_id):

    return song_queues.setdefault(
        guild_id,
        []
    )


# =========================================================
# Play Next
# =========================================================

async def play_next(
    guild,
    text_channel
):

    queue = get_queue(guild.id)

    voice = guild.voice_client

    if not queue:
        return

    if not voice:
        return

    if not voice.is_connected():
        return

    query = queue.pop(0)

    try:

        player = await YTDLSource.from_url(
            query
        )

        def after_play(error):

            if error:
                print(
                    f"[FFMPEG ERROR] {error}"
                )

            future = asyncio.run_coroutine_threadsafe(
                play_next(
                    guild,
                    text_channel
                ),
                bot.loop
            )

            try:
                future.result()
            except Exception as e:
                print(
                    f"[QUEUE ERROR] {e}"
                )

        voice.play(
            player,
            after=after_play
        )

        await text_channel.send(
            f"🎵 **تشغيل التالي:** `{player.title}`"
        )

    except Exception as e:

        print(
            f"[NEXT ERROR] "
            f"{type(e).__name__}: {e}"
        )

        await text_channel.send(
            "❌ ما قدرت أشغل الأغنية.\n"
            f"`{type(e).__name__}: {e}`"
        )

        if queue:
            await play_next(
                guild,
                text_channel
            )


# =========================================================
# Ready
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ Logged in as {bot.user}"
    )

    print(
        f"🎧 Owner Voice ID: "
        f"{OWNER_VOICE_CHANNEL_ID}"
    )

    for guild in bot.guilds:

        await connect_owner_channel(
            guild
        )


# =========================================================
# Keep Bot in Owner Room
# =========================================================

@bot.event
async def on_voice_state_update(
    member,
    before,
    after
):

    if not bot.user:
        return

    if member.id != bot.user.id:
        return

    owner_channel = get_owner_channel(
        member.guild
    )

    if owner_channel is None:
        return

    if (
        after.channel is None
        or after.channel.id != owner_channel.id
    ):

        print(
            "⚠️ Bot left owner channel. "
            "Reconnecting..."
        )

        await asyncio.sleep(2)

        await connect_owner_channel(
            member.guild
        )


# =========================================================
# Messages
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    content = message.content.strip()

    # -----------------------------------------------------
    # ش = Play song
    # -----------------------------------------------------

    if content.startswith("ش "):

        query = content[2:].strip()

        if not query:

            await message.channel.send(
                "اكتب اسم الأغنية بعد `ش`.\n"
                "مثال: `ش Fading`"
            )

            return

        if not user_in_owner_channel(message):

            await message.channel.send(
                "🔒 لازم تكون داخل روم الأونرات "
                "حتى تستخدم أوامر الأغاني."
            )

            return

        voice = await connect_owner_channel(
            message.guild,
            message
        )

        if not voice:
            return

        queue = get_queue(
            message.guild.id
        )

        if (
            voice.is_playing()
            or voice.is_paused()
        ):

            queue.append(query)

            await message.channel.send(
                f"📝 تمت إضافة `{query}` للقائمة."
            )

            return

        try:

            async with message.channel.typing():

                player = await YTDLSource.from_url(
                    query
                )

            def after_play(error):

                if error:
                    print(
                        f"[FFMPEG ERROR] {error}"
                    )

                future = asyncio.run_coroutine_threadsafe(
                    play_next(
                        message.guild,
                        message.channel
                    ),
                    bot.loop
                )

                try:
                    future.result()
                except Exception as e:
                    print(
                        f"[QUEUE ERROR] {e}"
                    )

            voice.play(
                player,
                after=after_play
            )

            await message.channel.send(
                f"🎵 **جاري التشغيل:** `{player.title}`"
            )

        except Exception as e:

            print(
                f"[PLAY ERROR] "
                f"{type(e).__name__}: {e}"
            )

            await message.channel.send(
                "❌ صار خطأ أثناء تحميل الأغنية.\n"
                f"`{type(e).__name__}: {e}`"
            )

    # -----------------------------------------------------
    # س = Skip
    # -----------------------------------------------------

    elif content == "س":

        if not user_in_owner_channel(message):
            return

        voice = message.guild.voice_client

        if voice and voice.is_playing():

            voice.stop()

            await message.channel.send(
                "⏭️ تم تخطي الأغنية."
            )

        else:

            await message.channel.send(
                "لا يوجد شيء شغال حالياً."
            )

    # -----------------------------------------------------
    # وقف = Stop + Clear Queue
    # -----------------------------------------------------

    elif content == "وقف":

        if not user_in_owner_channel(message):
            return

        queue = get_queue(
            message.guild.id
        )

        queue.clear()

        voice = message.guild.voice_client

        if voice:

            if (
                voice.is_playing()
                or voice.is_paused()
            ):

                voice.stop()

        await message.channel.send(
            "🛑 تم إيقاف التشغيل ومسح القائمة."
        )

    await bot.process_commands(message)


# =========================================================
# Start Bot
# =========================================================

token = os.getenv(
    "DISCORD_TOKEN"
)

if not token:

    raise RuntimeError(
        "❌ DISCORD_TOKEN غير موجود في Environment Variables."
    )

bot.run(token)
```
