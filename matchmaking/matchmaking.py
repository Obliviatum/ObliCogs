import asyncio, time
from typing import Union
from difflib import get_close_matches

# Discord.py
import discord

# Red
from redbot.core import checks, commands, Config
from redbot.core.bot import Red
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions
# from redbot.core.utils.chat_formatting import humanize_list

class Matchmaking(commands.Cog):

	__version__ = "1.0.9"
	__author__ = "Obliviatum"

	def __init__(self, bot: Red):
		self.bot = bot
		self.default_cooldown = 900 # 900 = 15 minutes
		self.AM = discord.AllowedMentions(roles=True, users=True) # AllowMentions
		self.DM = discord.AllowedMentions(roles=False, users=False) # DenyMentions

		# Using Red Config to store Data
		self.config = Config.get_conf(self, identifier=424914245973442562, force_registration=True)
		defaul_guild = {
			'games':{},
			'settings':{
				'check_vc':None, # Check connected to voice channel
				'check_gn':None, # Check game name activity
				'allowlist':{
					'users':[], # List of user.id
					'roles':[], # List of role.id
				},
				'denylist':{
					'users':[], # List of user.id
					'roles':[], # List of role.id
				}
			}
		}
		self.config.register_guild(**defaul_guild)

		# Using this to gain data accessing performance via RAM
		self.games = {}
		self.settings = {}
		self.lockcommand = {}

	#=============================Command Function==============================
	@commands.group(aliases=['mm'], invoke_without_command=True)
	@commands.guild_only()
	async def matchmaking(self, ctx: commands.Context, *, game_name:str=None):
		"""Let players know you wanna play a certain multiplayer game."""
		member: discord.Member = ctx.author

		#----Check if member did pass a game_name else return a list of game----
		if game_name is None:
			return await self.send_game_list(ctx)

		#----------------Check if bot got permission to mention-----------------
		if not ctx.channel.permissions_for(ctx.me).mention_everyone:
			return await ctx.send('I require the "Mention Everyone" permission to execute that command.')

		#------------Locking command at guild level to disable spam ping---------
		if self.lock_command(ctx):
			return await ctx.send('Someone else is current using this command. Please wait and retry soon.')

		#-----------------------Check if game in list---------------------------
		games = await self.get_games(ctx)
		game_name = game_name if game_name in games else await self.find_game_name(ctx, game_name)

		if game_name is None:
			# Couldn't find the game or a close match in the list.
			self.unlock_command(ctx)
			return await self.send_game_list(ctx)

		#---------------------Get role_object from game-------------------------
		role_id = games.get(game_name).get('role_id')
		role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)

		if role is None:
			# if role is None then it doesn't exist anymore
			self.unlock_command(ctx)
			return await ctx.send('Well, I found the game, but the corresponding @role doesn\'t exists anymore. Please contact a moderator for more information.')

		#---------Check if member.id or member.roles is on denylist---------
		denylist =  await self.get_settings(ctx, 'denylist')
		usercheck =  member.id in denylist.get('users')
		rolecheck = [r for r in [mr.id for mr in member.roles] if r in denylist.get('roles')]
		on_deny_list = any([usercheck, rolecheck])
		if on_deny_list:
			self.unlock_command(ctx)
			return await ctx.send(f'Sorry {member.mention}, you\'re not allowed to run this command. Contact a moderator for more information.')

		#---------Check if member.id or member.roles is on allowlist------------
		allowlist =  await self.get_settings(ctx, 'allowlist')
		usercheck =  member.id in allowlist.get('users')
		rolecheck = [r for r in [mr.id for mr in member.roles] if r in allowlist.get('roles')]
		on_allow_list = any([usercheck, rolecheck])
		if not on_allow_list:
			# This part will be skipped is on allowlist
			#---------------Check if member is in Voice Channel-----------------
			if await self.get_settings(ctx, 'check_vc') is True and member.voice is None:
				self.unlock_command(ctx)
				return await ctx.send('You must first join a voice channel before you can use this command.')

			#---------------Check if member is playing the game-----------------
			if await self.get_settings(ctx, 'check_gn') is True:
				activities = member.activities

				if activities is None:
					self.unlock_command(ctx)
					return await ctx.send(f'Don\'t see any activity on you {member.mention}. Either you have to start the game or share your game activity before you can use this command.')

				playing = None
				for activity in activities:
					if activity.type is discord.ActivityType.playing:
						playing = activity.name
						break

				if playing is None:
					self.unlock_command(ctx)
					return await ctx.send(f'Don\'t see you\'re playing a game {member.mention}. Either you have to start the game or share your game activity before you can use this command.')

				if playing != game_name:
					self.unlock_command(ctx)
					return await ctx.send(f'You\'re not currently playing `{game_name}`, but playing `{playing}`.')

			#-----------------Check if member has game role---------------------
			if role not in member.roles:
				self.unlock_command(ctx)
				return await ctx.send(f'You need to have {role.mention} before you can use this command for `{game_name}`.')


		#-----------------Check if game command is on Cooldown------------------
		wait_until = await self.get_wait_until(ctx, game_name)
		if wait_until > time.time():
			self.unlock_command(ctx)
			return await self.send_cooldown_message(ctx, game_name, wait_until)

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
	async def vccheck(self, ctx: commands.Context, state:bool=None):
		"""Enable or Disable command restriction for users in voicechannel only."""
		check_vc = await self.get_settings(ctx, 'check_vc')

		if state is None:
			if check_vc is None or not check_vc:
				state = True
			else:
				state = False

		if check_vc == state:
			return await ctx.send(f'The current state to check if user is in voicechannel is already set to `{check_vc}`.')

		await self.add_settings(ctx, 'check_vc', state)
		await ctx.send(f'Voicechannel check is set to `{state}`')

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def gncheck(self, ctx: commands.Context, state:bool=None):
		"""Enable or Disable command restriction for users with game name as activity."""
		check_gn = await self.get_settings(ctx, 'check_gn')

		if state is None:
			if check_gn is None or not check_gn:
				state = True
			else:
				state = False

		if check_gn == state:
			return await ctx.send(f'The current state to check if user is playing the game is already set to `{check_gn}`.')

		await self.add_settings(ctx, 'check_gn', state)
		await ctx.send(f'Game name activity check is set to `{state}`')


	#----------------------------Allowlist Command------------------------------
	@matchmaking.group(name="allowlist", aliases=['al'])
	@checks.guildowner_or_permissions(administrator=True)
	async def matchmaking_allowlist(self, ctx: commands.Context):
		"""Manage allowlist."""

	@matchmaking_allowlist.command(name="add")
	async def matchmaking_allowlist_add(self, ctx: commands.Context, *, role_or_user: Union[discord.Role, discord.User]):
		"""Add a role or user to allowlist."""
		key = 'allowlist'
		check = await self.check_settings(ctx, key, role_or_user)
		if not check:
			return await ctx.send(f'You first have to remove {role_or_user.mention} from denylist before you can add to allowlist. '
								  f'Use `{ctx.prefix}mm allowlist del {role_or_user.mention}` to do so.', allowed_mentions=self.DM)

		result = await self.add_settings(ctx, key, role_or_user)
		if result:
			await ctx.send(f'{role_or_user.mention} has been succesfull added to {key}.', allowed_mentions=self.DM)
		else:
			await ctx.send(f'{role_or_user.mention} has already been added to {key}', allowed_mentions=self.DM)

	@matchmaking_allowlist.command(name="del")
	async def matchmaking_allowlist_del(self, ctx: commands.Context, *, role_or_user: Union[discord.Role, discord.User]):
		"""Delete a role or user from allowlist."""
		key = 'allowlist'
		result = await self.del_settings(ctx, key, role_or_user)

		if result:
			await ctx.send(f'{role_or_user.mention} has been succesfull deleted from {key}.', allowed_mentions=self.DM)
		else:
			await ctx.send(f'{role_or_user.mention} has already been deleted from {key}', allowed_mentions=self.DM)

	@matchmaking_allowlist.command(name="list")
	async def matchmaking_allowlist_list(self, ctx: commands.Context):
		"""Return roles and user on allowlist."""
		allowlist = await self.get_settings(ctx, 'allowlist')
		rolelist = allowlist.get('roles', [])
		userlist = allowlist.get('users', [])

		if (rolelist or userlist):
			text = '>>> **Allowlist**\n'
		else:
			text = 'The allowlist is empty.'

		if rolelist:
			text += 'Roles:\n'
			for role_id in rolelist:
				role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)
				text += f'{role.mention}\n' if role else f'<@&{role_id}> ID:{role_id}\n'

		if userlist:
			text += 'Users:\n'
			for user_id in userlist:
				user = discord.utils.find(lambda u: u.id == user_id, ctx.guild.members)
				text += f'{user.mention}\n' if user else f'<@{user_id}> ID:{user_id}\n'

		await ctx.send(text, allowed_mentions=self.DM)


	#-----------------------------Denylist Command------------------------------
	@matchmaking.group(name="denylist", aliases=['dl'])
	@checks.guildowner_or_permissions(administrator=True)
	async def matchmaking_denylist(self, ctx: commands.Context):
		"""Manage denylist."""

	@matchmaking_denylist.command(name="add")
	async def matchmaking_denylist_add(self, ctx: commands.Context, *, role_or_user: Union[discord.Role, discord.User]):
		"""Add a role or user to denylist."""
		key = 'denylist'
		check = await self.check_settings(ctx, key, role_or_user)
		if not check:
			return await ctx.send(f'You first have to remove {role_or_user.mention} from allowlist before you can add to denylist. '
								  f'Use `{ctx.prefix}mm allowlist del {role_or_user.mention}` to do so.', allowed_mentions=self.DM)

		result = await self.add_settings(ctx, key, role_or_user)
		if result:
			await ctx.send(f'{role_or_user.mention} has been succesfull added to {key}.', allowed_mentions=self.DM)
		else:
			await ctx.send(f'{role_or_user.mention} has already been added to {key}', allowed_mentions=self.DM)

	@matchmaking_denylist.command(name="del")
	async def matchmaking_denylist_del(self, ctx: commands.Context, *, role_or_user: Union[discord.Role, discord.User]):
		"""Delete a role or user from denylist."""
		key = 'denylist'
		result = await self.del_settings(ctx, key, role_or_user)
		if result:
			await ctx.send(f'{role_or_user.mention} has been succesfull deleted from {key}.', allowed_mentions=self.DM)
		else:
			await ctx.send(f'{role_or_user.mention} has already been deleted from {key}', allowed_mentions=self.DM)

	@matchmaking_denylist.command(name="list")
	async def matchmaking_denylist_list(self, ctx: commands.Context):
		"""Return roles and user on denylist."""
		denylist = await self.get_settings(ctx, 'denylist')
		rolelist = denylist.get('roles', [])
		userlist = denylist.get('users', [])

		if (rolelist or userlist):
			text = '>>> **Denylist**\n'
		else:
			text = 'The denylist is empty.'

		if rolelist:
			text += 'Roles:\n'
			for role_id in rolelist:
				role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)
				text += f'{role.mention}\n' if role else f'<@&{role_id}> ID:{role_id}\n'

		if userlist:
			text += 'Users:\n'
			for user_id in userlist:
				user = discord.utils.find(lambda u: u.id == user_id, ctx.guild.members)
				text += f'{user.mention}\n' if user else f'<@{user_id}> ID:{user_id}\n'

		await ctx.send(text, allowed_mentions=self.DM)


	#------------------------Debug activity game name---------------------------
	@matchmaking.command()
	@checks.is_owner()
	async def activity(self, ctx: commands.Context, member: discord.Member=None):
		"""Test command for debuging author activity."""
		if member is None:
			member: discord.Member = ctx.author
		activities = member.activities

		if activities is None:
			return await ctx.send(f'Don\'t see any activity on {member}.')

		for activity in activities:
			if activity.type is discord.ActivityType.playing:
				return await ctx.send(f'{member} is playing {activity.name}.')

		await ctx.send(f'I see some activity on {member}, but no game activity.')


	#===========================Fucntion to haddle stuff========================
	async def find_game_name(self, ctx, game_name):
		games = await self.get_games(ctx)
		match = get_close_matches(game_name, games.keys(), 1, 0.3)
		if not match:
			# No match was found. Returing a list of games.
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

			# role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)
			txt += f'`{game_name}` | <@&{role_id}> | {cooldown_fmt} # {time_fmt}\n'

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
	def time_format(seconds: int):
		if seconds:
			h, r = divmod(seconds, 60 * 60)
			m, s = divmod(r, 60)
			data = {'hour':h, 'minute':m, 'second':s}

			times = [
				f'{v} {k}' + ('s' if v > 1 else '')
				for k, v in data.items()
				if v != 0
			]

			for i in range(-len(times)+1, 0):
				times.insert(i, ' and ' if i == -1 else ', ')
			msg = ''.join(times)

			# msg = humanize_list(times)
		else:
			msg = 'No Cooldown'

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

	#---------------------------------Settings---------------------------------
	async def get_settings(self, ctx, key=None):
		guild_id = str(ctx.guild.id)
		settings = self.settings.get(guild_id)

		if settings is None:
			guild_group = self.config.guild(ctx.guild)
			settings = await guild_group.settings()
			self.settings.update({guild_id:settings})

		if key is None:
			return settings
		else:
			return settings.get(key)

	async def add_settings(self, ctx, key, value):
		guild_id = str(ctx.guild.id)
		settings = await self.get_settings(ctx)

		if key in ['allowlist', 'denylist']:
			if isinstance(value, discord.Role):
				skey = 'roles'
			elif isinstance(value, discord.User):
				skey = 'users'
			if value.id not in settings[key][skey]:
				settings[key][skey].append(value.id)
			else:
				return False # This value is already set

		elif key in ['check_vc', 'check_gn']:
			settings[key] = value

		# else:
		# 	return None # No key match found

		await self.config.guild(ctx.guild).settings.set(settings)
		self.settings.update({guild_id:settings})
		return True # add value to settings completed succesfull

	async def del_settings(self, ctx, key, value):
		guild_id = str(ctx.guild.id)
		settings = await self.get_settings(ctx)

		if key in ['allowlist', 'denylist']:
			if isinstance(value, discord.Role):
				skey = 'roles'
			elif isinstance(value, discord.User):
				skey = 'users'
			try:
				settings[key][skey].remove(value.id)
			except ValueError:
				return False # This value doens't exists in the list

		elif key in ['check_vc', 'check_gn']:
			settings[key] = None

		await self.config.guild(ctx.guild).settings.set(settings)
		self.settings.update({guild_id:settings})
		return True # delete value from settings completed succesfull

	async def check_settings(self, ctx, key, value):
		# Check if value
		guild_id = str(ctx.guild.id)
		settings = await self.get_settings(ctx)

		if key in ['allowlist', 'denylist']:
			otherkey = 'allowlist' if key is 'denylist' else 'denylist'
			if isinstance(value, discord.Role):
				skey = 'roles'
			elif isinstance(value, discord.User):
				skey = 'users'

			if value.id in settings[otherkey][skey]:
				return False # value also exists on the other list.
		return True # value doesn't exists on the other list
