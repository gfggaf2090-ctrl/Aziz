import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
from collections import deque
import os
from flask import Flask
from threading import Thread

# إعداد Flask للحفاظ على البوت نشط
app = Flask('')

@app.route('/')
def home():
    return "✅ البوت يعمل بنجاح!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# إعدادات البوت
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="", intents=intents)

# قائمة الأغاني لكل سيرفر
queues = {}

# إعدادات yt-dlp
ytdl_options = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -af dynaudnorm=f=200'
}

ytdl = yt_dlp.YoutubeDL(ytdl_options)

class MusicPlayer:
    def __init__(self, guild, channel):
        self.guild = guild
        self.channel = channel
        self.queue = deque()
        self.current = None
        self.voice_client = None
        
    async def search_song(self, query):
        """بحث عن الأغنية"""
        try:
            if query.startswith('http'):
                info = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ytdl.extract_info(query, download=False)
                )
            else:
                info = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=False)
                )
                if 'entries' in info:
                    info = info['entries'][0]
            
            return {
                'title': info.get('title'),
                'url': info.get('url'),
                'webpage_url': info.get('webpage_url'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail')
            }
        except Exception as e:
            print(f"Error: {e}")
            return None
    
    async def play_next(self):
        """تشغيل الأغنية التالية"""
        if len(self.queue) > 0:
            song = self.queue.popleft()
            self.current = song
        else:
            self.current = None
            return
        
        try:
            source = discord.FFmpegPCMAudio(song['url'], **ffmpeg_options)
            self.voice_client.play(
                source,
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    self.play_next(), bot.loop
                )
            )
            
            embed = discord.Embed(
                title="🎧 يتم التشغيل الآن",
                description=f"**{song['title']}**",
                color=discord.Color.green()
            )
            
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song['thumbnail'])
            
            duration = song.get('duration')
            if duration:
                mins, secs = divmod(duration, 60)
                embed.add_field(name="المدة", value=f"{mins}:{secs:02d}")
            
            await self.channel.send(embed=embed)
        except Exception as e:
            print(f"Playback error: {e}")
            await self.channel.send(f"❌ خطأ في التشغيل")
            await self.play_next()

@bot.event
async def on_ready():
    print(f'✅ تم تسجيل الدخول: {bot.user}')
    print('✅ البوت جاهز!')
    print(f'✅ متصل بـ {len(bot.guilds)} سيرفر')
    
    # تحديث حالة البوت
    status_loop.start()

@tasks.loop(minutes=5)
async def status_loop():
    """تحديث حالة البوت"""
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="🎧 ش [اسم الأغنية]"
        )
    )

@bot.event
async def on_voice_state_update(member, before, after):
    """التحقق من مغادرة البوت للروم"""
    if member == bot.user and after.channel is None:
        if member.guild.id in queues:
            del queues[member.guild.id]

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    content = message.content.strip()
    content_lower = content.lower()
    
    # أمر ش أو شغل
    if content_lower.startswith(('ش ', 'شغل ')):
        # استخراج اسم الأغنية
        if content_lower.startswith('ش '):
            query = content[2:].strip()
        else:
            query = content[4:].strip()
        
        if not query:
            await message.channel.send("❌ اكتب اسم الأغنية! مثال: `ش يا طير`")
            return
        
        if not message.author.voice:
            await message.channel.send("❌ ادخل الروم الصوتي أولاً!")
            return
        
        voice_channel = message.author.voice.channel
        
        if message.guild.id not in queues:
            queues[message.guild.id] = MusicPlayer(message.guild, message.channel)
        
        player = queues[message.guild.id]
        
        if not player.voice_client:
            player.voice_client = await voice_channel.connect()
        elif player.voice_client.channel != voice_channel:
            await player.voice_client.move_to(voice_channel)
        
        search_msg = await message.channel.send("🔍 جاري البحث...")
        
        song = await player.search_song(query)
        
        if not song:
            await search_msg.edit(content="❌ ما لقيت الأغنية!")
            return
        
        player.queue.append(song)
        
        if not player.voice_client.is_playing():
            await search_msg.delete()
            await player.play_next()
        else:
            embed = discord.Embed(
                title="➕ تمت الإضافة للقائمة",
                description=f"**{song['title']}**",
                color=discord.Color.blue()
            )
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song['thumbnail'])
            await search_msg.edit(content=None, embed=embed)
    
    # أمر وقف
    elif content_lower in ['وقف', 'pause']:
        if message.guild.id in queues:
            player = queues[message.guild.id]
            if player.voice_client and player.voice_client.is_playing():
                player.voice_client.pause()
                await message.channel.send("⏸️ تم الإيقاف المؤقت")
            else:
                await message.channel.send("❌ ما في أغنية تشتغل!")
    
    # أمر كمل
    elif content_lower in ['كمل', 'resume']:
        if message.guild.id in queues:
            player = queues[message.guild.id]
            if player.voice_client and player.voice_client.is_paused():
                player.voice_client.resume()
                await message.channel.send("▶️ تم المتابعة")
            else:
                await message.channel.send("❌ الأغنية مش متوقفة!")
    
    # أمر تخطى
    elif content_lower in ['تخطى', 'skip', 'التالي']:
        if message.guild.id in queues:
            player = queues[message.guild.id]
            if player.voice_client and player.voice_client.is_playing():
                player.voice_client.stop()
                await message.channel.send("⏭️ تم التخطي")
            else:
                await message.channel.send("❌ ما في أغنية تشتغل!")
    
    # أمر ايقاف
    elif content_lower in ['ايقاف', 'stop', 'اطلع']:
        if message.guild.id in queues:
            player = queues[message.guild.id]
            if player.voice_client:
                player.queue.clear()
                await player.voice_client.disconnect()
                del queues[message.guild.id]
                await message.channel.send("⏹️ تم الإيقاف")
            else:
                await message.channel.send("❌ البوت مش متصل!")
    
    # أمر القائمة
    elif content_lower in ['القائمة', 'قائمة', 'queue']:
        if message.guild.id in queues:
            player = queues[message.guild.id]
            
            if not player.current and len(player.queue) == 0:
                await message.channel.send("❌ القائمة فاضية!")
                return
            
            embed = discord.Embed(
                title="📜 قائمة التشغيل",
                color=discord.Color.purple()
            )
            
            if player.current:
                embed.add_field(
                    name="🎧 الأغنية الحالية",
                    value=player.current['title'],
                    inline=False
                )
            
            if len(player.queue) > 0:
                queue_list = "\n".join([
                    f"{i+1}. {song['title']}" 
                    for i, song in enumerate(list(player.queue)[:10])
                ])
                embed.add_field(
                    name=f"القادم ({len(player.queue)} أغنية)",
                    value=queue_list,
                    inline=False
                )
            
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ القائمة فاضية!")
    
    # أمر الحالية
    elif content_lower in ['الحالية', 'الحين', 'np', 'nowplaying']:
        if message.guild.id in queues:
            player = queues[message.guild.id]
            if player.current:
                embed = discord.Embed(
                    title="🎧 الأغنية الحالية",
                    description=f"**{player.current['title']}**",
                    color=discord.Color.green()
                )
                if player.current.get('thumbnail'):
                    embed.set_thumbnail(url=player.current['thumbnail'])
                
                duration = player.current.get('duration')
                if duration:
                    mins, secs = divmod(duration, 60)
                    embed.add_field(name="المدة", value=f"{mins}:{secs:02d}")
                
                await message.channel.send(embed=embed)
            else:
                await message.channel.send("❌ ما في أغنية تشتغل!")
    
    # أمر الأوامر
    elif content_lower in ['الأوامر', 'اوامر', 'help', 'مساعدة']:
        embed = discord.Embed(
            title="🎧 قائمة الأوامر",
            description="أوامر البوت الموسيقي",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="ش [اسم الأغنية]",
            value="تشغيل أغنية من YouTube\nمثال: `ش يا طير` أو `شغل حماسي`",
            inline=False
        )
        embed.add_field(name="وقف", value="إيقاف مؤقت", inline=True)
        embed.add_field(name="كمل", value="متابعة التشغيل", inline=True)
        embed.add_field(name="تخطى", value="تخطي الأغنية", inline=True)
        embed.add_field(name="ايقاف", value="إيقاف كامل والخروج", inline=True)
        embed.add_field(name="القائمة", value="عرض قائمة الأغاني", inline=True)
        embed.add_field(name="الحالية", value="الأغنية اللي تشتغل الحين", inline=True)
        embed.set_footer(text="🎧 بوت موسيقي 24/7")
        
        await message.channel.send(embed=embed)

# تشغيل البوت
if __name__ == "__main__":
    keep_alive()
    
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if not TOKEN:
        print("❌ خطأ: DISCORD_TOKEN غير موجود في متغيرات البيئة!")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ خطأ في تشغيل البوت: {e}")
