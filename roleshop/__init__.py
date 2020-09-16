from .roleshop import Roleshop
import asyncio

async def setup(bot):
	obj = bot.add_cog(Roleshop(bot))
	if asyncio.iscoroutine(obj):
		await obj
