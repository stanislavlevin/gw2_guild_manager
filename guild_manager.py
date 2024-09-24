import asyncio
import aiohttp
import configparser
from urllib.parse import quote


# https://docs.aiohttp.org/en/stable/client_advanced.html#limiting-connection-pool-size
# default: 100
OPEN_CONNECTIONS_LIMIT = 50


async def agw2mists_user_profile(name):
    user_name_quoted = quote(name)
    USER_PROFILE_URL = f"https://api.gw2mists.com/profile/{user_name_quoted}"
    headers = {
        "referer": "https://gw2mists.com",
        "origin": "https://gw2mists.com",
        "accept": "application/json",
    }
    connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
    async with aiohttp.ClientSession(
        connector=connector, headers=headers, raise_for_status=True
    ) as session:
        async with session.get(USER_PROFILE_URL) as response:
            profile = await response.json()
            profile["name"] = name
            return profile


async def auser_profiles(names):
    tasks = [agw2mists_user_profile(name) for name in names]
    return await asyncio.gather(*tasks)


async def agw2mists_guild_profile(name):
    guild_name_quoted = quote(name)
    guild_profile_url = f"https://api.gw2mists.com/guilds/{guild_name_quoted}"
    headers = {
        "referer": "https://gw2mists.com",
        "origin": "https://gw2mists.com",
        "accept": "application/json",
    }
    connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
    async with aiohttp.ClientSession(
        connector=connector, headers=headers, raise_for_status=True
    ) as session:
        async with session.get(guild_profile_url) as response:
            return await response.json()


async def agw2_guild_profile(gid, api_key):
    guild_profile_url = f"https://api.guildwars2.com/v2/guild/{gid}/members"
    headers = {
        "authorization": f"Bearer {api_key}",
        "accept": "application/json",
    }
    connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
    async with aiohttp.ClientSession(
        connector=connector, headers=headers, raise_for_status=True
    ) as session:
        async with session.get(guild_profile_url) as response:
            profile = await response.json()
            return (gid, profile)


async def agw2_guild_profiles(guilds):
    tasks = [agw2_guild_profile(*guild) for guild in guilds]
    return await asyncio.gather(*tasks)


GUILD_NAME = "Dodge Right I Mean"
print("*** guild name ***")
print(GUILD_NAME)
print()

ALLIANCE_GUILD_NAME = "Glub Glub Glub Glub Glub"
print("*** alliance guild name ***")
print(ALLIANCE_GUILD_NAME)
print()

print("*** public data (gw2mists) ***")
guild_profile = asyncio.run(agw2mists_guild_profile(GUILD_NAME))

print("*** total guild member count (gw2mists) ***")
print(guild_profile["member_count"])
print()

not_registered_names = {
    x["name"] for x in guild_profile["member"] if x["registered"] == 0
}
print(
    "*** guild members not registered on gw2mists.com "
    f"(total: {len(not_registered_names)}) ***"
)
for name in sorted(not_registered_names):
    print(name)
print()

guild_team_id = guild_profile["team_id"]
wrong_team_names = {
    x["name"] for x in guild_profile["member"] if x["team_id"] != guild_team_id
}
wrong_team_names = wrong_team_names - not_registered_names

print(
    f"*** guild members on wrong team (total: {len(wrong_team_names)}) ***"
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
    "*** guild members having 0 kills during current match "
    f"(total: {len(inactive_names)}) ***"
)

for name in sorted(inactive_names):
    print(name)
print()

nothaving_wvw_names = {
    x["name"] for x in user_profiles if "wvw_guild" not in x
}
print(
    "*** guild members not having wvw permission in gw2mists API key "
    f"(total: {len(nothaving_wvw_names)}) ***"
)
for name in sorted(nothaving_wvw_names):
    print(name)
print()

print(
    "*** private data (gw2, requires guild and alliance leader's API KEY) ***"
)
config = configparser.ConfigParser()
config.read("settings.ini")

guilds_ids = (
    (config[guild_name]["gid"], config[guild_name]["api_key"])
    for guild_name in (GUILD_NAME, ALLIANCE_GUILD_NAME)
)

guild_profiles_gw2 = asyncio.run(agw2_guild_profiles(guilds_ids))
guild_profiles_gw2 = {k:v for k,v in guild_profiles_gw2}
guild_id = config[GUILD_NAME]["gid"]
guild_profile_gw2 = guild_profiles_gw2[guild_id]
guild_member_names = {x["name"] for x in guild_profile_gw2}

print("*** total guild member count (gw2 api) ***")
print(len(guild_member_names))
print()

alliance_guild_id = config[ALLIANCE_GUILD_NAME]["gid"]
alliance_profile_gw2 = guild_profiles_gw2[alliance_guild_id]
alliance_member_names = {x["name"] for x in alliance_profile_gw2}

not_alliance_members = guild_member_names - alliance_member_names
print(
    "*** guild members that didn't join alliance "
    f"(total: {len(not_alliance_members)}) ***"
)
for name in sorted(not_alliance_members):
    print(name)
print()

inactive_and_not_alliance_names = inactive_names & not_alliance_members
print(
    "*** inactive guild members that didn't join alliance "
    f"(total: {len(inactive_and_not_alliance_names)}) ***"
)

for name in sorted(inactive_and_not_alliance_names):
    print(name)
print()
