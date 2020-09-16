import asyncio, time
from difflib import get_close_matches

# Discord.py
import discord

# Red
from redbot.core import checks, commands, Config
from redbot.core.bot import Red
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions

# Thanks stack overflow http://stackoverflow.com/questions/21872366/plural-string-formatting
class PluralDict(dict):
	def __missing__(self, key):
		if '(' in key and key.endswith(')'):
			key, rest = key.split('(', 1)
			value = super().__getitem__(key)
			suffix = rest.rstrip(')').split(',')
			if len(suffix) == 1:
				suffix.insert(0, '')
			return suffix[0] if value <= 1 else suffix[1]
		raise KeyError(key)

class Matchmaking(commands.Cog):

	__version__ = "1.0.4"
	__author__ = "Obliviatum"

	def __init__(self, bot: Red):
		self.bot = bot
		self.default_cooldown = 900 # 900 = 15 minutes

		# Using Red Config to store Data
		self.config = Config.get_conf(self, identifier=424914245973442562, force_registration=True)
		self.config.register_guild(games={}, check_vc=None)

		# Using this to gain data accessing performance via RAM
		self.games = {}
		self.check_vc = {}
		self.lockcommand = {}

	#=============================Command Function==============================
	@commands.group(aliases=['mm'], invoke_without_command=True)
	@commands.guild_only()
	async def matchmaking(self, ctx: commands.Context, *, game_name:str=None):
		"""Let players know you wanna play a certain multiplayer game."""
		#----------------Check if bot got permission to mention-----------------
		if not ctx.channel.permissions_for(ctx.me).mention_everyone:
			return await ctx.send('I require the "Mention Everyone" permission to execute that command.')

		#----------------Check if member is in Voice Channel--------------------
		if await self.get_check_vc(ctx) and ctx.author.voice is None:
			return await ctx.send('You must first join a voice channel before you can use this command.')

		#------------Locking command at guild level to disable spam ping---------
		guild_id = str(ctx.guild.id)
		if self.lock_command(ctx):
			return await ctx.send('Someone else is current using this command. Please wait and retry soon.')

		if game_name is None:
			# Send a list of games.
			self.unlock_command(ctx)
			return await self.send_game_list(ctx)

		#-----------------------Check if game in list---------------------------
		guild_group = self.config.guild(ctx.guild)
		games = await guild_group.games()

		game_name = game_name if game_name in games else await self.find_game_name(ctx, games, game_name)

		if game_name is None:
			# Couldn't find the game or a close match in the list.
			self.unlock_command(ctx)
			return

		#-----------------Check if game command is on Cooldown------------------
		wait_until = await self.get_wait_until(ctx, game_name)
		if wait_until > time.time():
			self.unlock_command(ctx)
			return await self.send_cooldown_message(ctx, game_name, wait_until)

		role_id = games.get(game_name).get('role_id')

		#---------------------Get role_object from game-------------------------
		role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)

		if role is None:
			# if role is None then it doesn't exist anymore
			self.unlock_command(ctx)
			return await ctx.send('Well, I found the game, but the corresponding @role doesn\'t exists anymore')

		#--------------------Mention players for matchmaking--------------------
		await self.set_wait_until(ctx, game_name)
		await ctx.send(
			f'{ctx.author.mention} is looking to play {game_name}! Hop in {role.mention}!',
			allowed_mentions=discord.AllowedMentions(roles=True)
		)
		self.unlock_command(ctx)

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def add(self, ctx: commands.Context, role: discord.Role, *, game_name:str):
		"""Add a game with corresponding @role to a list."""
		games = await self.get_games(ctx)
		if game_name in games:
			return await ctx.send(f'The game `{game_name}` already has been added to list.')

		await self.add_game(ctx, game_name, role)
		await ctx.tick()

	@matchmaking.command(name='del', aliases=['delete'])
	@checks.guildowner_or_permissions(administrator=True)
	async def delete(self, ctx: commands.Context, *, game_name:str):
		"""Delete a game from the list."""
		games = await self.get_games(ctx)
		if game_name not in games:
			return await ctx.send(f'The game `{game_name}` doesn\'t exists on the list.')

		await self.del_game(ctx, game_name)
		await ctx.tick()

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def cooldown(self, ctx: commands.Context, cooldown:int=None, *, game_name:str=None):
		"""Manage the duration for command cooldown in seconds for each game"""

		if (cooldown and game_name) is None:
			# retuen list of games and there info
			return await self.send_setting_games(ctx)

		if not game_name:
			return await ctx.send(f'You didn\'t give me a name of a game. Please `{ctx.prefix}cooldown {cooldown} <game_name>`')

		games = await self.get_games(ctx)
		if game_name not in games:
			return await ctx.send(f'The game `{game_name}` doesn\'t exists on the list.')

		pref_cooldown = await self.get_cooldown(ctx, game_name)
		if not cooldown:
			time_fmt = self.time_format(pref_cooldown)
			return await ctx.send(f'The current cooldown is set to: {time_fmt}')

		await self.set_cooldown(ctx, game_name, cooldown)
		time_fmt = self.time_format(cooldown)
		await ctx.send(f'The cooldown been changed to: {time_fmt}')

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def cleardata(self, ctx: commands.Context):
		"""This will remove all the saved data"""
		await self.config.clear_all()
		self.games = {}
		await ctx.tick()

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def resetcooldown(self, ctx: commands.Context, *, game_name:str=None):
		"""This will reset cooldown for a given game or all games if no game is given"""
		games = await self.get_games(ctx)
		if game_name is not None:
			if game_name not in games:
				return await ctx.send(f'The game `{game_name}` doesn\'t exists on the list.')
			await self.set_wait_until(ctx, game_name, 0)
			await ctx.tick()
			return

		for game_name in games:
			await self.set_wait_until(ctx, game_name, 0)
		await ctx.tick()

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def vccheck (self, ctx: commands.Context, state:bool=None):
		"""Enable or Disable command for users in voicechannel only."""
		check_vc = await self.get_check_vc(ctx)

		if state is None:
			if check_vc is None or not check_vc:
				state = True
			else:
				state = False

		if check_vc == state:
			await ctx.send(f'The current state to check if user is in voicechannel is already set to `{check_vc}`.')
			return

		await self.set_check_vc(ctx, state)
		await ctx.send(f'Voicechannel check is set to `{state}`')

	#===========================Fucntion to haddle stuff========================
	async def find_game_name(self, ctx, games, game_name):
		match = get_close_matches(game_name, games.keys(), 1, 0.3)
		if not match:
			# No match was found. Returing a list of games.
			await self.send_game_list(ctx)
			return

		# Found a match.
		msg = await ctx.send(f'I can\'t find a game called `{game_name}`.\nDid you mean `{match[0]}`?')
		start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

		try: # Wait for a reaction on question
			pred = ReactionPredicate.yes_or_no(msg, ctx.author)
			await ctx.bot.wait_for("reaction_add", check=pred, timeout=15)
		except asyncio.TimeoutError:
			await ctx.send("You didn\'t react in time, canceling.")

		try: # Delete reactions from question message
			if ctx.channel.permissions_for(ctx.me).manage_messages:
				await msg.clear_reactions()
		except:
			pass

		if pred.result is not True:
			return # User didn't responded with tick

		game_name = match[0]
		return game_name

	async def send_game_list(self, ctx):
		games = await self.get_games(ctx)

		#---------------------Check if there is a list of game------------------
		if games is None:
			return await ctx.send("There are currently no games on the list.")

		#---------------------Create a game list message------------------------
		name_games = [n for n in games.keys()]
		await ctx.send('>>> **Games list:**\n' + '\n'.join(name_games))

	async def send_setting_games(self, ctx):
		games = await self.get_games(ctx)

		#---------------------Check if there is a list of game------------------
		if games is None:
			return await ctx.send("There are current no games added to the list.")

		#---------------------Create a game ifno message------------------------
		txt = '>>> **Games settings list:**\n'
		for game_name, info in games.items():
			role_id = info['role_id']
			cooldown = info['cooldown']
			wait_until = info['wait_until']
			seconds_left = round(wait_until - time.time())
			time_fmt = self.time_format(seconds_left)
			cooldown_fmt = self.time_format(cooldown)

			role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)
			txt += f'`{game_name}` | {role.mention} | {cooldown_fmt} # {time_fmt}\n'

		await ctx.send(txt)


	async def send_cooldown_message(self, ctx, game_name, wait_until):
		now = time.time()
		seconds_left = round(wait_until - now)
		time_fmt = self.time_format(seconds_left)
		await ctx.send(f'Sorry {ctx.author.mention}, but this command is currently on cooldown for `{game_name}`. You can try again in {time_fmt}.')

	def lock_command(self, ctx):
		guild_id = str(ctx.guild.id)
		if self.lockcommand.get(guild_id, False):
			return True
		self.lockcommand.update({guild_id:True})
		return False

	def unlock_command(self, ctx):
		guild_id = str(ctx.guild.id)
		self.lockcommand.update({guild_id:False})

	@staticmethod
	def time_format(seconds):
		m, s = divmod(seconds, 60)
		h, m = divmod(m, 60)
		data = PluralDict({'hour': h, 'minute': m, 'second': s})
		if h > 0:
			fmt = "{hour} hour{hour(s)}"
			if data["minute"] > 0 and data["second"] > 0:
				fmt += ", {minute} minute{minute(s)}, and {second} second{second(s)}"
			if data["second"] > 0 == data["minute"]:
				fmt += ", and {second} second{second(s)}"
			msg = fmt.format_map(data)
		elif h == 0 and m > 0:
			if data["second"] == 0:
				fmt = "{minute} minute{minute(s)}"
			else:
				fmt = "{minute} minute{minute(s)}, and {second} second{second(s)}"
			msg = fmt.format_map(data)
		elif m == 0 and h == 0 and s > 0:
			fmt = "{second} second{second(s)}"
			msg = fmt.format_map(data)
		else:
			msg = "No Cooldown"
		return msg


	#==============================Caching Function=============================
	#-----------------------------------Games-----------------------------------
	async def get_games(self, ctx):
		guild_id = str(ctx.guild.id)
		games = self.games.get(guild_id)

		if games is None:
			guild_group = self.config.guild(ctx.guild)
			games = await guild_group.games()
			self.games.update({guild_id:games})

		return games

	async def add_game(self, ctx, game_name, role):
		guild_id = str(ctx.guild.id)
		games = await self.get_games(ctx)

		games[game_name] = {
			'role_id':role.id,
			'cooldown':self.default_cooldown,
			'wait_until':0
		}

		await self.config.guild(ctx.guild).games.set(games)
		self.games.update({guild_id:games})

	async def del_game(self, ctx, game_name):
		guild_id = str(ctx.guild.id)
		games = await self.get_games(ctx)

		try:
			del games[game_name]
		except KeyError:
			pass

		await self.config.guild(ctx.guild).games.set(games)
		self.games.update({guild_id:games})

	#---------------------------------Cooldown----------------------------------
	async def get_cooldown(self, ctx, game_name):
		guild_id = str(ctx.guild.id)
		cooldown = self.games.get(guild_id, {}).get(game_name, {}).get('cooldown')

		if cooldown is None:
			games = await self.get_games(ctx)
			cooldown = games.get(game_name).get('cooldown')

		return cooldown

	async def set_cooldown(self, ctx, game_name, cooldown):
		guild_id = str(ctx.guild.id)
		games = await self.get_games(ctx)

		games[game_name]['cooldown'] = cooldown

		await self.config.guild(ctx.guild).games.set(games)
		self.games.update({guild_id:games})

	#---------------------------------Wait Until--------------------------------
	async def get_wait_until(self, ctx, game_name):
		guild_id = str(ctx.guild.id)
		wait_until = self.games.get(guild_id, {}).get(game_name, {}).get('wait_until')

		if wait_until is None:
			games = await self.get_games(ctx)
			wait_until = games.get(game_name, {}).get('wait_until', 0)

		return wait_until

	async def set_wait_until(self, ctx, game_name, cooldown=None):
		guild_id = str(ctx.guild.id)
		games = await self.get_games(ctx)

		# Calculate wait until time
		now = time.time()
		cooldown = cooldown if cooldown is not None else await self.get_cooldown(ctx, game_name)
		wait_until = round(now + cooldown)

		games[game_name]['wait_until'] = wait_until

		await self.config.guild(ctx.guild).games.set(games)
		self.games.update({guild_id:games})

	#---------------------------------check_vc----------------------------------
	async def get_check_vc(self, ctx):
		guild_id = str(ctx.guild.id)
		check_vc = self.check_vc.get(guild_id)

		if check_vc is None:
			guild_group = self.config.guild(ctx.guild)
			check_vc = await guild_group.check_vc()
			self.check_vc.update({guild_id:check_vc})

		return check_vc

	async def set_check_vc(self, ctx, bool):
		guild_id = str(ctx.guild.id)
		await self.config.guild(ctx.guild).check_vc.set(bool)
		self.check_vc.update({guild_id:bool})
