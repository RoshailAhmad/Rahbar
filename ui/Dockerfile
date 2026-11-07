# RAHBAR ui image: static chat page served by nginx as a non-root user.
# Build context: ui/   ->   docker build -t rahbar-ui:dev ui
# nginx.conf listens on 8080 and writes only under /tmp (an emptyDir on the cluster).
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
# 101 is the nginx user in the unprivileged image.
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
