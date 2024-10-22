# malachite

Email domain banlist manager

Malachite stores a list of patterns (domains and IP addresses) for known bad email providers.

When a user registers or changes the email on their account, malachite will resolve the MX, A,
and AAAA records of the email address's domain. If it matches an item on the banlist, a services
`BADMAIL` entry is added for that domain, and the account is `FDROP`ed (if registering) or
`FREEZE`'d (if changing the email). If `FDROP`ed, the user is sent a `NOTICE`, asking them to
try a different email address.

## Setup

```sh
cp config.example.toml config.toml
$EDITOR config.toml
psql -U malachite -f make-database.sql
```

## Running

```
python3 -m malachite config.toml
```

## Commands

**ADD**
```
usage: ADD <ip|domain> <reason>
  add an ip or domain to the mxbl
```

**DEL**
```
usage: DEL <id>
  remove an ip or domain from the mxbl
```

**EDITPATTERN**
```
usage: EDITPATTERN <id> <ip|domain>
  update the ip or domain for a pattern by id
```

**EDITREASON**
```
usage: EDITREASON <id> <reason>
  update the reason for a pattern by id
```

**GET**
```
usage: GET <id>
  get information about a specific mxbl entry
```

**HELP**
```
usage: HELP [command]
  show usage information about a command
```

**LIST**
```
usage: LIST [limit = 0] [glob]
  list mxbl entries up to limit (default: no limit),
  optionally filtering with a glob pattern
```

**TOGGLE**
```
usage: TOGGLE <id>
  enable or disable an entry
```
