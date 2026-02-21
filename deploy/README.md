# Docker Production Deployment

This folder contains a production-oriented single-container deployment for real hardware.

## 1. Prepare host directories

```bash
sudo mkdir -p /srv/opencane/{config,workspace,data,backups}
sudo chown -R $USER:$USER /srv/opencane
```

## 2. Prepare config and env

1. Initialize a default config once (outside compose):

```bash
docker run --rm -v /srv/opencane:/root/.opencane iflabx/opencane:latest onboard
```

2. Move config to the external path expected by compose:

```bash
cp /srv/opencane/config.json /srv/opencane/config/config.json
```

3. Create runtime secrets file from template:

```bash
cp deploy/runtime.env.example /srv/opencane/runtime.env
```

Then edit `/srv/opencane/runtime.env` and set real keys/tokens/broker values.

## 3. Start service

```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

## 4. Verify runtime

```bash
curl http://127.0.0.1:18792/v1/runtime/status
curl http://127.0.0.1:18792/v1/runtime/observability
```

## 5. Upgrade

```bash
docker compose -f deploy/docker-compose.prod.yml pull
docker compose -f deploy/docker-compose.prod.yml up -d
```

## 6. Backup baseline

Back up these paths regularly:

- `/srv/opencane/config/config.json`
- `/srv/opencane/data`
- `/srv/opencane/workspace`
