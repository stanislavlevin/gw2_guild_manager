import asyncio
import aiohttp
import configparser
import copy
from urllib.parse import quote


# https://docs.aiohttp.org/en/stable/client_advanced.html#limiting-connection-pool-size
# default: 100
OPEN_CONNECTIONS_LIMIT = 50


class GW2MISTS_GUILD:
    API_ENDPOINT = "https://api.gw2mists.com"
    API_HEADERS = {
        "referer": "https://gw2mists.com",
        "origin": "https://gw2mists.com",
        "accept": "application/json",
    }

    def __init__(self, guild_name):
        self.guild_name = guild_name
        self._profile = None
        self._unregistered_members = None
        self._team_id = None
        self._wrongteam_members = None
        self._registered_members = None
        self._currentmatch_members = None
        self._members_profiles = None
        self._inactive_members = None
        self._members = None

    async def amember_profile(self, name):
        user_name_quoted = quote(name)
        user_profile_url = f"{self.API_ENDPOINT}/profile/{user_name_quoted}"
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
        async with aiohttp.ClientSession(
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=True,
        ) as session:
            async with session.get(user_profile_url) as response:
                profile = await response.json()
                profile["name"] = name
                return profile

    async def amember_profiles(self, names):
        tasks = [self.amember_profile(name) for name in names]
        return await asyncio.gather(*tasks)

    async def aguild_profile(self):
        guild_name_quoted = quote(self.guild_name)
        guild_profile_url = f"{self.API_ENDPOINT}/guilds/{guild_name_quoted}"
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
        async with aiohttp.ClientSession(
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=True,
        ) as session:
            async with session.get(guild_profile_url) as response:
                return await response.json()

    @property
    def profile(self):
        if self._profile is None:
            self._profile = copy.deepcopy(asyncio.run(self.aguild_profile()))
        return self._profile

    @property
    def unregistered_members(self):
        if self._unregistered_members is None:
            self._unregistered_members = frozenset(
                (
                    x["name"]
                    for x in self.profile["member"]
                    if x["registered"] == 0
                )
            )
        return self._unregistered_members

    @property
    def members(self):
        if self._members is None:
            self._members = frozenset(
                (x["name"] for x in self.profile["member"])
            )
        return self._members

    @property
    def team_id(self):
        if self._team_id is None:
            self._team_id = self.profile["team_id"]
        return self._team_id

    @property
    def wrongteam_members(self):
        if self._wrongteam_members is None:
            self._wrongteam_members = frozenset(
                {
                    x["name"]
                    for x in self.profile["member"]
                    if x["team_id"] != self.team_id
                } - self.unregistered_members
            )
        return self._wrongteam_members

    @property
    def registered_members(self):
        if self._registered_members is None:
            self._registered_members = frozenset(
                (
                    x["name"]
                    for x in self.profile["member"]
                    if x["registered"] == 1
                )
            )
        return self._registered_members

    @property
    def currentmatch_members(self):
        if self._currentmatch_members is None:
            self._currentmatch_members = frozenset(
                self.registered_members - self.wrongteam_members
            )
        return self._currentmatch_members

    @property
    def members_profiles(self):
        if self._members_profiles is None:
            self._members_profiles = asyncio.run(
                self.amember_profiles(self.currentmatch_members)
            )
        return self._members_profiles

    @property
    def inactive_members(self):
        if self._inactive_members is None:
            self._inactive_members = frozenset(
                (
                    x["name"]
                    for x in self.members_profiles
                    if x["stats"]["kills"] < 100
                )
            )
        return self._inactive_members


class GW2_GUILD:
    API_ENDPOINT = "https://api.guildwars2.com"
    API_HEADERS = {
        "accept": "application/json",
    }

    def __init__(self, guild_name):
        self.guild_name = guild_name

        config = configparser.ConfigParser()
        config.read("settings.ini")
        if self.guild_name not in config:
            raise ValueError(
                f"not configured guild: {self.guild_name}, "
                "see settings.ini.in for details"
            )
        self.gid = config[self.guild_name]["gid"]
        self.api_key = config[self.guild_name]["api_key"]
        self.API_HEADERS["authorization"] =  f"Bearer {self.api_key}"
        self._profile = None
        self._members = None

    async def aguild_profile(self):
        guild_profile_url = f"{self.API_ENDPOINT}/v2/guild/{self.gid}/members"
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
        async with aiohttp.ClientSession(
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=True,
        ) as session:
            async with session.get(guild_profile_url) as response:
                return await response.json()

    @property
    def profile(self):
        if self._profile is None:
            self._profile = copy.deepcopy(asyncio.run(self.aguild_profile()))
        return self._profile

    @property
    def members(self):
        if self._members is None:
            self._members = frozenset((x["name"] for x in self.profile))
        return self._members


GUILD_NAME = "Dodge Right I Mean"
print("*** guild name ***")
print(GUILD_NAME)
print()

ALLIANCE_GUILD_NAME = "Glub Glub Glub Glub Glub"
print("*** alliance guild name ***")
print(ALLIANCE_GUILD_NAME)
print()

print("*** public data (gw2mists) ***")
gw2mist_guild = GW2MISTS_GUILD(GUILD_NAME)

print("*** total guild member count (gw2mists) ***")
print(gw2mist_guild.profile["member_count"])
print()

print(
    "*** guild members not registered on gw2mists.com "
    f"(total: {len(gw2mist_guild.unregistered_members)}) ***"
)
for name in sorted(gw2mist_guild.unregistered_members):
    print(name)
print()

print(
    "*** guild members on wrong team "
    f"(total: {len(gw2mist_guild.wrongteam_members)}) ***"
)
for name in sorted(gw2mist_guild.wrongteam_members):
    print(name)
print()

print(
    "*** guild members having less than 100 kills during current match "
    f"(total: {len(gw2mist_guild.inactive_members)}) ***"
)

for name in sorted(gw2mist_guild.inactive_members):
    print(name)
print()

print(
    "*** private data (gw2, requires guild and alliance leader's API KEY) ***"
)
gw2_guild = GW2_GUILD(GUILD_NAME)
print("*** total guild member count (gw2 api) ***")
print(len(gw2_guild.members))
print()

gw2_alliance = GW2_GUILD(ALLIANCE_GUILD_NAME)
print("*** total alliance member count (gw2 api) ***")
print(len(gw2_alliance.members))
print()

unregistered_not_alliance_members = (
    gw2mist_guild.unregistered_members - gw2_alliance.members
)
print(
    "*** not registered guild members that didn't join alliance "
    f"(total: {len(unregistered_not_alliance_members)}) ***"
)
for name in sorted(unregistered_not_alliance_members):
    print(name)
print()

gw2_not_alliance_members = gw2_guild.members - gw2_alliance.members
print(
    "*** guild members that didn't join alliance "
    f"(total: {len(gw2_not_alliance_members)}) ***"
)
for name in sorted(gw2_not_alliance_members):
    print(name)
print()

inactive_and_not_alliance_names = (
    gw2mist_guild.inactive_members & gw2_not_alliance_members
)
print(
    "*** inactive guild members that didn't join alliance "
    f"(total: {len(inactive_and_not_alliance_names)}) ***"
)

for name in sorted(inactive_and_not_alliance_names):
    print(name)
print()
