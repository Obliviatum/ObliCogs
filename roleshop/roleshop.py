import asyncio
from typing import Union
from difflib import get_close_matches

# Discord.py
import discord

# Red
from redbot.core import bank, checks, commands, Config
from redbot.core.bot import Red
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions


emoji_numbers = ['1️⃣', '2️⃣', '3️⃣',
				 '4️⃣', '5️⃣', '6️⃣',
				 '7️⃣', '8️⃣', '9️⃣',
				 '🔟']

class Roleshop(commands.Cog):

	__version__ = "1.0.0a1"
	__author__ = "Obliviatum"

	def __init__(self, bot: Red):
		self.bot = bot
		self.config = Config.get_conf(self, identifier=424914245973442562, force_registration=True)
		default_guild = {
			"roles":{},
			"sorted":[],
			"settings":{
				"shop_channel_id":None,
				"shop_message_id":None,
				"bot_channel_id":None
			}
		}
		self.config.register_guild(**default_guild)

	@commands.group(autohelp=True)
	@commands.guild_only()
	# @checks.guildowner_or_permissions(administrator=True)
	@commands.is_owner()
	async def roleshop(self, ctx: commands.Context):
		"""Role shop group command"""
		pass

	@roleshop.command()
	async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
		"""Sets a channel for the shop"""
		guild = ctx.guild

		# if not channel.permissions_for(ctx.me).manage_channels: # needed to be able to create a text channel
		# 	return

		# overwrite = discord.PermissionOverwrite()
		# overwrite.send_messages = False
		# overwrite.read_messages = False

		# overwrites = {
		# 	guild.default_role: discord.PermissionOverwrite(read_messages=False)
		# 	# guild.me: discord.PermissionOverwrite(read_messages=True)
		# }

		# shop_channel = await guild.create_text_channel('Roleshop🛒', overwrite=overwrite, reason='Created a channel to put the roleshop message in. Members can buy certain roles by reaction on this message.')

		# guild_group = self.config.guild(ctx.guild)

	@roleshop.command()
	async def open(self, ctx: commands.Context):
		"""Creates a message with role to buy"""
		guild = ctx.guild
		channel = ctx.channel
		message = ctx.message

		guild_group = self.config.guild(ctx.guild)

		roles = await guild_group.roles()
		list = await guild_group.sorted()
		currency = await bank.get_currency_name(ctx.guild)

		# Create a embed message with roles to buy in it
		embed, emojis = self.created_embed(list, roles, guild, currency)

		msg = await ctx.send(embed=embed)
		await asyncio.gather(*(msg.add_reaction(emoji) for emoji in emojis))

		await guild_group.settings.shop_channel_id.set(channel.id)
		await guild_group.settings.shop_message_id.set(msg.id)


	@roleshop.command()
	async def adit(self, ctx: commands.Context, *, role: Union[discord.Role, int, str]):
		"""add or edit a @role to or from the shop"""
		guild = ctx.guild
		author = ctx.author
		channel = ctx.channel

		guild_group = self.config.guild(guild)

		#--------------------------Which role?----------------------------------

		isrole = isinstance(role, discord.Role)
		if not isrole:
			role = await self.guess_role(ctx, role)
		if role is None:
			return

		#--------------------------Role Cost?-----------------------------------
		roles = await guild_group.roles()
		role_id = str(role.id)
		role_edit = roles.get(role_id)

		if role_edit is not None:
			price_now = role_edit.get('price')
			await ctx.send(f'The price of `{role}` now is {price_now:,}. What may the new price be?')
		else:
			await ctx.send(f'What may the price be for `{role}`?')

		def check(m): # check if reaction is coming from author and same channel
			return m.author == author and m.channel == channel

		try:
			answer = await self.bot.wait_for("message", check=check, timeout=15)
		except asyncio.TimeoutError:
			await ctx.send("You didn\'t react on time, canceling.")
			return

		try:
			price = int(answer.content)
		except ValueError:
			await ctx.send('Sorry, that isn\'t a number, canceling.')
			return

		#------------------------Add/edit role to shop--------------------------
		currency = await bank.get_currency_name(guild)
		max_bal = await bank.get_max_balance(guild)

		if len(currency) > 1: # Check if currency pronounced as €20 or 20 credits
			str_price = f'{price:,} {currency}'
		else:
			str_price = f'{currency}{price:,}'

		if price > max_bal:
			await ctx.send(f'Sorry, the cost of {str_price} is to high, becuase the maximum balance is set to {max_bal}.')
			return

		await ctx.send(f'adding {role} for {str_price} to the shop.')

		role_settings = {
			role_id:{
				'id':role.id,
				'price':price,
				'group':None # This will be added in the future
			}
		}

		roles.update(role_settings)
		list = sorted(roles.keys(), key=lambda x: -roles[x]['price'])
		#                                         ^ This reveses the sorting
		list = [int(i) for i in list] # Converting str to int

		await guild_group.roles.set(roles)
		await guild_group.sorted.set(list)

		#-----------------------Update shop message-----------------------------
		settings = await guild_group.settings()
		shop_message_id = settings.get('shop_message_id')
		if shop_message_id is None:
			return # When guild opend a shop yet
		shop_channel_id = settings.get('shop_channel_id')

		channel = self.bot.get_channel(shop_channel_id)
		message = await channel.fetch_message(shop_message_id)

		embed, emojis = self.created_embed(list, roles, guild, currency)
		await message.edit(embed=embed)
		if len(message.reactions) == len(emojis):
			pass
		elif len(message.reactions) > len(emojis):
			for reaction in message.reaction:
				if reaction.me and reaction.emoji not in emojis:
					await reaction.remove(self.bot.user)
		elif len(message.reactions) < len(emojis):
			rea_emojis = [r.emoji for r in message.reactions]
			await asyncio.gather(*(message.add_reaction(emoji) for emoji in emojis if emoji not in rea_emojis))

	@roleshop.command()
	async def remove(self, ctx: commands.Context, *, role: Union[discord.Role, int, str]):
		"""remove a @role from the shop"""
		guild = ctx.guild
		author = ctx.author
		channel = ctx.channel

		guild_group = self.config.guild(guild)

		#--------------------------Which role?----------------------------------

		isrole = isinstance(role, discord.Role)
		if not isrole:
			role = await self.guess_role(ctx, role)
		if role is None:
			return

		#--------------------------Remove role----------------------------------
		roles = await guild_group.roles()
		role_id = str(role.id)

		try:
			del roles[role_id]
			await ctx.send(f'`{role}` is removed from the shop.')
		except KeyError:
			await ctx.send(f'`{role}` doens\'t exist in the shop.')
			return

		list = sorted(roles.keys(), key=lambda x: -roles[x]['price'])
		#                                         ^ This reveses the sorting
		list = [int(i) for i in list] # Converting str to int

		await guild_group.roles.set(roles)
		await guild_group.sorted.set(list)

		#-----------------------Update shop message-----------------------------
		#guild, list, roles
		currency = await bank.get_currency_name(guild)
		settings = await guild_group.settings()
		shop_message_id = settings.get('shop_message_id')
		if shop_message_id is None:
			return # When guild opend a shop yet
		shop_channel_id = settings.get('shop_channel_id')

		channel = self.bot.get_channel(shop_channel_id)
		message = await channel.fetch_message(shop_message_id)

		embed, emojis = self.created_embed(list, roles, guild, currency)
		await message.edit(embed=embed)
		if len(message.reactions) == len(emojis):
			pass
		elif len(message.reactions) > len(emojis):
			for reaction in message.reactions:
				if reaction.me and reaction.emoji not in emojis:
					await reaction.clear()
		elif len(message.reactions) < len(emojis):
			rea_emojis = [r.emoji for r in message.reactions]
			await asyncio.gather(*(message.add_reaction(emoji) for emoji in emojis if emoji not in rea_emojis))


	@roleshop.command()
	@commands.is_owner()
	async def test(self, ctx: commands.Context, *, role: Union[discord.Role, int, str]):
	# async def test(self, ctx: commands.Context, *, role: discord.Role):
		"""Testing stuff"""

		user = ctx.author
		channel = ctx.channel

		message = await channel.send(f'Hi {user.mention},\n Please read the rules in the message above and react with `I agree` to declare that you have read and fully understand them.')

		def check_message(m):
			# Check if message is coming from the user and was said in same channel
			return m.author == user and m.channel == channel

		def check_leave(m):
			# Check if it's the member you're waiting for
			return m == user

		tasks = [
			self.bot.wait_for('message', check=check_message),
			self.bot.wait_for('member_remove', check=check_leave)
		]
		done, pending = await asyncio.wait(tasks, timeout=10, return_when=asyncio.FIRST_COMPLETED)

		if not done:
			# User didn't react or didn't leave between given timeout
			await message.delete()
			return

		for task in done:
			result = task.result()
			if isinstance(result, discord.Message):
				# User did response with a message
				msg = result
			elif isinstance(result, discord.Member):
				# User did leave before leaving a reaction
				await message.delete()
				return

	@roleshop.command()
	async def showsettings(self, ctx: commands.Context):
		"""Shows server settings"""
		guild = ctx.guild
		guild_group = self.config.guild(guild)
		settings = await guild_group.settings()
		await ctx.send(settings)

	@roleshop.command()
	async def showroles(self, ctx: commands.Context):
		"""Shows server settings"""
		guild = ctx.guild
		guild_group = self.config.guild(guild)
		roles = await guild_group.roles()
		await ctx.send(roles)

	@staticmethod
	async def guess_role(ctx, role):
		roles = ctx.guild.roles

		if isinstance(role, int): # if role is passed as role.id
			guild_roles = [str(r.id) for r in roles]
			match = get_close_matches(str(role), guild_roles, 1, 0.3)
			if match:
				role_obj = discord.utils.get(roles, id=int(match[0]))
				msg = await ctx.send(f'I can\'t find a role with id `{role}`.\nDid you mean `{match[0]}` - {role_obj}?')
				start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
			else:
				await ctx.send(f'I can\'t find a role with id `{role}`')
				return
			# await self.bot.wait_for('reaction_add',) #comment out on 2020-09-15

		elif isinstance(role, str): # If role is passed as role.name
			guild_roles = [r.name for r in roles]
			match = get_close_matches(role, guild_roles, 1, 0.3)
			if match:
				role_obj = discord.utils.get(roles, name=match[0])
				msg = await ctx.send(f'I can\'t find a role named `{role}`.\nDid you mean `{match[0]}`?')
				start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
			else:
				await ctx.send(f'I can\'t find a role named `{role}`')
				return

		try: # Wait for a reaction on question
			pred = ReactionPredicate.yes_or_no(msg, ctx.author)
			await ctx.bot.wait_for("reaction_add", check=pred, timeout=15)
		except asyncio.TimeoutError:
			await ctx.send("You didn\'t react on time, canceling.")

		try: # Delete reactions from message
			if msg.channel.permissions_for(ctx.me).manage_messages:
				await msg.clear_reactions()
		except:
			pass

		if pred.result is not True: # User didn't responded with tick
			return

		return role_obj

	@staticmethod
	def created_embed(list, roles, guild, currency):
		"""Create a embed message with roles to buy in it."""
		embed = discord.Embed(colour = 0x78b159)
		text = ''

		i=0
		emojis = []
		for id in list:
			role_id = str(id)
			price = roles.get(role_id).get('price')
			role_obj = discord.utils.get(guild.roles, id=id)
			if role_obj:
				emoji = emoji_numbers[i]

				if len(currency) > 1:
					text += f'{emoji}{role_obj.mention} {price:,} {currency}\n'
				else:
					text += f'{emoji}{role_obj.mention} {currency}{price:,}\n'
				emojis.append(emoji)
				i += 1
		embed.add_field(name="Roles:", value=text)
		embed.set_footer(text='React with the corresponding emoji to buy a role!')
		# embed.set_footer(text='You can only have one role of this list')
		return embed, emojis

	@commands.Cog.listener()
	async def on_raw_reaction_add(self, payload):
		try:
			#---------------------Check reaction is valid-----------------------
			emoji = payload.emoji
			if emoji.name not in emoji_numbers:
				return

			# user = self.bot.get_user(payload.user_id)
			user_id = payload.user_id
			if user_id == self.bot.user.id:
				return # When reaction is coming from bot

			guild = self.bot.get_guild(payload.guild_id)
			if not guild:
				return # When reaction not from valid guild

			guild_group = self.config.guild(guild)

			roles = await guild_group.roles()
			if roles is None:
				return # When no roles where set in guild

			settings = await guild_group.settings()

			shop_channel_id = settings.get('shop_channel_id')
			if shop_channel_id is None:
				return # When no shop channel is set
			if int(shop_channel_id) != payload.channel_id:
				return # When reaction is not coming from shop channel

			shop_message_id = settings.get('shop_message_id')
			if shop_message_id is None:
				return
			if int(shop_message_id) != payload.message_id:
				return


			#---------------------Create objects from payload-----------------------
			try:
				channel = self.bot.get_channel(payload.channel_id)
				message = await channel.fetch_message(payload.message_id)
			except:
				return

			index = emoji_numbers.index(emoji.name) # Get index role

			shoplist = await guild_group.sorted()
			role_id = shoplist[index]
			price = roles.get(str(role_id)).get('price')

			role = discord.utils.find(lambda r: r.id == role_id, guild.roles)
			member = guild.get_member(user_id)

			# Check if member already has the role
			if role in member.roles:
				await member.send(f'You already have `{role}`.')
				# FUTURE OPTION: able to sel the role for half the money
				return

			# Check if member can spend that role
			if not await bank.can_spend(member, price):
				await member.send(f'Sorry, you don\'t have anough money to buy `{role}`.')
				return

			await member.add_roles(role)
			new_balance = await bank.withdraw_credits(member, price)
			await member.send(f'You\'re now proud owner of `{role}`.')


		except Exception as e:
			s = str(e)
			await self.bot.send_to_owners(f'Error: roleshop - on_raw_reaction_add\n{s}')

		# @commands.Cog.listener()
		# async def on_raw_reaction_remove(self, payload):
		# # listen to remove so user can remove there role?
