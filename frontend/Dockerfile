FROM node:22.14.0-alpine3.21 AS build
WORKDIR /app
ARG VITE_DEMO_MODE=false
ARG VITE_AUTH_LOGIN_URL=
ARG VITE_AUTH_CLIENT_ID=
ARG VITE_AUTH_REDIRECT_URI=
ENV VITE_DEMO_MODE=$VITE_DEMO_MODE
ENV VITE_AUTH_LOGIN_URL=$VITE_AUTH_LOGIN_URL
ENV VITE_AUTH_CLIENT_ID=$VITE_AUTH_CLIENT_ID
ENV VITE_AUTH_REDIRECT_URI=$VITE_AUTH_REDIRECT_URI
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM nginxinc/nginx-unprivileged:1.27.4-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
