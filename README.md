# malachite

Email domain banlist manager

Malachite stores a list of patterns (domains and IP addresses) for known bad email providers.

When a user registers or changes the email on their account, malachite will resolve the MX, A,
and AAAA records of the email address's domain. If it matches an item on the banlist, a services
`BADMAIL` entry is added for that domain, and the account is `FDROP`ed (if registering) or
`FREEZE`'d (if changing the email). If `FDROP`ed, the user is sent a `NOTICE`, asking them to
try a different email address. If it does not match an item on the banlist, it is added to
a cache with a configured TTL. If a pattern is added or edited, any cached domains that match the
new pattern are evicted from the cache.

## Setup

```sh
cp config.example.toml config.toml
$EDITOR config.toml
psql -U malachite -f make-database.sql
```

## Running

```sh
python3 -m malachite config.toml
```

## Commands

**ADD**
```
usage: ADD <ip|cidr|domain|%glob%|/regex/> <reason>
  add a pattern to the mxbl. globs and regexes are case-insensitive.
  Patterns are added at WARN status level. Use SET <id> LETHAL to activate
  a pattern fully.
```

**CACHE**
```
usage: CACHE <SHOW|DEL> [name]
  view or modify the clean domain cache
```

**EDITPATTERN**
```
usage: EDITPATTERN <id> <ip|cidr|domain|%glob%|/regex/>
  update the pattern of an entry by id. This will copy the reason and
  status of the old entry but use the provided pattern. The old entry
  will be disabled.
```

**EDITREASON**
```
usage: EDITREASON <id> <reason>
  update the reason for an entry by id
```

**GET**
```
usage: GET <id>
  get information about an entry
```

**HELP**
```
usage: HELP [command]
  show usage information for a command
```

**LIST**
```
usage: LIST [limit = 0] [offset = 0]
  list enabled mxbl entries up to limit (default: no limit),
  starting at offset (default: index 0)
```

**LISTALL**
```
usage: LISTALL [limit = 0] [offset = 0]
  list all mxbl entries up to limit (default: no limit),
  starting at offset (default: index 0)
```

**SET**
```
usage: SET <id> <status>
  set an entry's status (LETHAL, WARN, OFF)
```

**SETTINGS**
```
usage: SETTINGS <GET|GETALL|SET> [name] [value]
  update dynamic settings for the bot
```

> *currently accepted settings:*
> - **pause**: `0` for normal operation, `1` to only warn

**TEST**
```
usage: TEST <email|domain>
  test if an email or domain would match an existing pattern
```

**TESTPAT**
```
usage: TESTPAT <ip|cidr|domain|%glob%|/regex/> <email|domain>
  test if an email or domain would match a specified pattern
```

## Patterns

Patterns can be one of:

- **domain**: must match the complete domain (with or without the root domain `.`)
- **IP address**: can be IPv4 or IPv6
- **CIDR range**: if an ip address is within the CIDR range, it matches. can be IPv4 or IPv6 in `a.b.c.d/N` or `aa:bb:cc:dd/N` format
- **glob**: uses Python [`fnmatch`](https://docs.python.org/3/library/fnmatch.html) globbing rules, can be matched to domains or IPs
- **regular expression**: uses Python [`re`](https://docs.python.org/3/library/re.html) rules, can be matched to domains or IPs
