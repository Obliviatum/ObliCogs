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

	__version__ = "1.0.0"
	__author__ = "Obliviatum"

	def __init__(self, bot: Red):
		self.bot = bot
		default_cooldown = 900 # 900 = 15 minutes

		# Using Red Config to store Data
		self.config = Config.get_conf(self, identifier=424914245973442562, force_registration=True)
		guild_default = {
			"games":{},
			"cooldown":default_cooldown,
		}
		self.config.register_guild(**guild_default)

		member_default = {
			"wait_until":0
		}
		self.config.register_member(**member_default)

		# Using this to gain data accessing performance via RAM
		self.games = {}
		self.cooldown = {}
		self.wait_until = {}


	#==============================Command Function=============================
	@commands.group(aliases=['mm'], invoke_without_command=True)
	@commands.guild_only()
	# @commands.bot_has_permissions(mention_everyone=True)
	async def matchmaking(self, ctx: commands.Context, *, game_name:str=None):
		"""Let players now you wanna play a certian multiplater game."""

		#------------------Check if bot got permission to mention---------------
		if not ctx.channel.permissions_for(ctx.me).mention_everyone:
			return await ctx.send('I require the "Mention Everyone" permission to execute that command')

		if game_name is None:
			# Send a list of games.
			return await self.send_game_list(ctx)

		#-------------------Check if member is on Cooldown----------------------
		wait_until = await self.get_wait_until(ctx)
		if wait_until > time.time():
			return await self.send_cooldown_message(ctx, wait_until)

		#-----------------------Check if game in list---------------------------
		guild_group = self.config.guild(ctx.guild)
		games = await guild_group.games()
		role_id = games.get(game_name, False)

		if not role_id:
			# Couldn't find the game in the list, Trying to find a close match.
			match = get_close_matches(game_name, games.keys(), 1, 0.3)
			if not match:
				# No match was found. Returing a list of games.
				return await self.send_game_list(ctx)

			# Found a match.
			msg = await ctx.send(f'I can\'t find a game named `{game_name}`.\nDid you mean `{match[0]}`?')
			start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)

			try: # Wait for a reaction on question
				pred = ReactionPredicate.yes_or_no(msg, ctx.author)
				await ctx.bot.wait_for("reaction_add", check=pred, timeout=15)
			except asyncio.TimeoutError:
				await ctx.send("You didn\'t react on time, canceling.")

			try: # Delete reactions from question message
				if ctx.channel.permissions_for(ctx.me).manage_messages:
					await msg.clear_reactions()
			except:
				pass

			if pred.result is not True:
				return # User didn't responded with tick

			game_name = match[0]
			role_id = games.get(game_name, False)

		#---------------------Get role_object from game-------------------------
		role = discord.utils.find(lambda r: r.id == role_id, ctx.guild.roles)

		if role is None:
			# This role doesn't exist anymore
			return await ctx.send('Well, I found the game, but the corresponding @role doesn\'t exists anymore')

		#--------------------Mention players for matchmaking--------------------
		await self.set_wait_until(ctx)
		await ctx.send(
			f'{ctx.author.mention} is looking to play {game_name}! Hop in {role.mention}!',
			allowed_mentions=discord.AllowedMentions(roles=True)
		)

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def add(self, ctx: commands.Context, role: discord.Role, *, game_name:str):
		"""Add a game with corresponding @role to a list."""
		games = await self.get_games(ctx)
		if game_name in games:
			return await ctx.send(f'The game `{game_name}` allready has been added to list.')

		await self.add_game(ctx, game_name, role)
		await ctx.tick()

	@matchmaking.command(name='del', aliases=['delete'])
	@checks.guildowner_or_permissions(administrator=True)
	async def delete(self, ctx: commands.Context, *, game_name:str):
		"""Delete a game with corresponding @role to a list."""
		games = await self.get_games(ctx)
		if game_name not in games:
			return await ctx.send(f'The game `{game_name}` doesn\'t exists in the list.')

		await self.del_game(ctx, game_name)
		await ctx.tick()

	@matchmaking.command()
	@checks.guildowner_or_permissions(administrator=True)
	async def cooldown(self, ctx: commands.Context, cooldown:int=False):
		"""Manage the duration for command cooldown in seconds"""
		pref_cooldown = await self.get_cooldown(ctx)
		if not cooldown:
			time_fmt = self.time_format(pref_cooldown)
			return await ctx.send(f'The current cooldown is set to: {time_fmt}')

		await self.set_cooldown(ctx, cooldown)
		time_fmt = self.time_format(cooldown)
		await ctx.send(f'The cooldown been changed to: {time_fmt}')


	#===========================Fucntion to haddle stuff========================
	async def send_game_list(self, ctx):
		guild_group = self.config.guild(ctx.guild)
		games = await guild_group.games()

		#---------------------Check if there is a list of game------------------
		if not games:
			return await ctx.send("There are current no games added to the list.")

		#---------------------Create a game list message------------------------
		name_games = [n for n in games.keys()]
		await ctx.send('>>> **Games list:**\n' + '\n'.join(name_games))

	async def send_cooldown_message(self, ctx, wait_until):
		now = time.time()
		seconds_left = round(wait_until - now)
		time_fmt = self.time_format(seconds_left)
		await ctx.send(f'Sorry {ctx.author.mention}, but you have to wait {time_fmt} before you can use this command again.')

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
		games = self.games.get(guild_id, False)

		if not games:
			guild_group = self.config.guild(ctx.guild)
			games = await guild_group.games()
			self.games[guild_id] = games

		return games

	async def add_game(self, ctx, game_name, role):
		guild_id = str(ctx.guild.id)
		games = await self.get_games(ctx)

		games[game_name] = role.id
		await self.config.guild(ctx.guild).games.set(games)
		self.games[guild_id] = games

	async def del_game(self, ctx, game_name):
		guild_id = str(ctx.guild.id)
		games = await self.get_games(ctx)

		try:
			del games[game_name]
		except KeyError:
			pass

		await self.config.guild(ctx.guild).games.set(games)
		self.games[guild_id] = games

	#---------------------------------Cooldown----------------------------------
	async def get_cooldown(self, ctx):
		guild_id = str(ctx.guild.id)
		cooldown = self.cooldown.get(guild_id, False)

		if not cooldown:
			guild_group = self.config.guild(ctx.guild)
			cooldown = await guild_group.cooldown()
			self.cooldown[guild_id] = cooldown

		return cooldown

	async def set_cooldown(self, ctx, cooldown):
		guild_id = str(ctx.guild.id)

		await self.config.guild(ctx.guild).cooldown.set(cooldown)
		self.cooldown[guild_id] = cooldown

	#---------------------------------Wait Until--------------------------------
	async def get_wait_until(self, ctx):
		guild_id = str(ctx.guild.id)
		member_id = str(ctx.author.id)

		wait_until = self.wait_until.get(guild_id, {}).get(member_id, None)

		if wait_until is None:
			member_group = self.config.member(ctx.author)
			wait_until = await member_group.wait_until()

			if guild_id not in self.wait_until:
				self.wait_until[guild_id] = {}
			self.wait_until[guild_id][member_id] = wait_until

		return wait_until

	async def set_wait_until(self, ctx):
		guild_id = str(ctx.guild.id)
		member_id = str(ctx.author.id)

		now = time.time()
		cooldown = await self.get_cooldown(ctx)
		wait_until = round(now + cooldown)

		await self.config.member(ctx.author).wait_until.set(wait_until)

		if guild_id not in self.wait_until:
			self.wait_until[guild_id] = {}
		self.wait_until[guild_id][member_id] = wait_until
