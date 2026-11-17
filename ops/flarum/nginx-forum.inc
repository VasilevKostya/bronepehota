# Insert into the existing HTTPS server block; the static root is unchanged.
location = /forum {
    return 308 https://bronepehota.leonet.site/forum/;
}
location /forum/ {
    proxy_pass http://127.0.0.1:8086/;
    proxy_http_version 1.1;
    proxy_set_header Host bronepehota.leonet.site;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host bronepehota.leonet.site;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header Connection "";
    proxy_redirect off;
    proxy_intercept_errors off;
    client_max_body_size 20m;
    proxy_read_timeout 60s;
}
