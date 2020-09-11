from .matchmaking import Matchmaking

async def setup(bot):
	cog = Matchmaking(bot)
	bot.add_cog(cog)
