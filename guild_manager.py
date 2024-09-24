import asyncio
import aiohttp
from urllib.parse import quote


async def agw2mists_user_profile(name):
    user_name_quoted = quote(name)
    USER_PROFILE_URL = f"https://api.gw2mists.com/profile/{user_name_quoted}"
    headers = {
        "referer": "https://gw2mists.com",
        "origin": "https://gw2mists.com",
        "accept": "application/json",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(USER_PROFILE_URL) as response:
            try:
                profile = await response.json()
                profile["name"] = name
                return profile
            except aiohttp.client_exceptions.ContentTypeError:
                print(await response.text())
                raise


async def auser_profiles(names):
    tasks = [agw2mists_user_profile(name) for name in names]
    return await asyncio.gather(*tasks)


async def agw2mists_guild_profile(name):
    guild_name_quoted = quote(name)
    GUILD_PROFILE_URL = f"https://api.gw2mists.com/guilds/{guild_name_quoted}"
    headers = {
        "referer": "https://gw2mists.com",
        "origin": "https://gw2mists.com",
        "accept": "application/json",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(GUILD_PROFILE_URL) as response:
            return await response.json()


GUILD_NAME = "Dodge Right I Mean"
guild_profile = asyncio.run(agw2mists_guild_profile(GUILD_NAME))

print("*** total member count ***")
print(guild_profile["member_count"])
print()

not_registered_names = {
    x["name"] for x in guild_profile["member"] if x["registered"] == 0
}
print(
    "*** members not registered on gw2mists.com "
    f"(total: {len(not_registered_names)}) ***"
)
for name in sorted(not_registered_names):
    print(name)
print()

print("*** current team id ***")
guild_team_id = guild_profile["team_id"]
print(guild_team_id)
print()

wrong_team_names = {
    x["name"] for x in guild_profile["member"] if x["team_id"] != guild_team_id
}
wrong_team_names = wrong_team_names - not_registered_names

print(
    f"*** members on wrong team (total: {len(wrong_team_names)}) ***"
)
for name in sorted(wrong_team_names):
    print(name)
print()

registered_names = {
    x["name"] for x in guild_profile["member"] if x["registered"] == 1
}
match_names = registered_names - wrong_team_names

user_profiles = asyncio.run(auser_profiles(match_names))

inactive_names = {
    x["name"] for x in user_profiles if x["stats"]["kills"] == 0
}
print(
    "*** members having 0 kills during current match "
    f"(total: {len(inactive_names)}) ***"
)

for name in sorted(inactive_names):
    print(name)
print()

nothaving_wvw_names = {
    x["name"] for x in user_profiles if "wvw_guild" not in x
}
print(
    "*** members not having wvw permission in gw2mists API key "
    f"(total: {len(nothaving_wvw_names)}) ***"
)
for name in sorted(nothaving_wvw_names):
    print(name)
print()
