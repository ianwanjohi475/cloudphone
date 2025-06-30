# Remote access

By default the dashboard (`:8080`) and ws-scrcpy (`:8000`) bind to the host. To
reach the farm from another machine, put them behind a TLS reverse proxy with
auth. **Never expose adb ports (5555+) to the internet.**

## Caddy (simplest — automatic HTTPS)

`Caddyfile`:

```
phones.example.com {
    basic_auth {
        admin <bcrypt-hash>      # caddy hash-password
    }
    handle_path /scrcpy/* {
        reverse_proxy localhost:8000
    }
    reverse_proxy localhost:8080
}
```

```bash
caddy run --config ./Caddyfile
```

## nginx

```nginx
server {
    listen 443 ssl;
    server_name phones.example.com;
    ssl_certificate     /etc/letsencrypt/live/phones.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/phones.example.com/privkey.pem;

    auth_basic "cloudphone";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / { proxy_pass http://127.0.0.1:8080; }

    location /scrcpy/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;     # WebSocket for scrcpy
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

## SSH tunnel (no public exposure)

```bash
ssh -L 8080:localhost:8080 -L 8000:localhost:8000 user@host
# then browse http://localhost:8080 locally
```

## Hardening reminders

- Firewall everything except 443 (`ufw default deny incoming`).
- Strong dashboard auth; rotate `DASHBOARD_SECRET`.
- Keep adb on the internal docker network only.
- See [security.md](security.md).
