import type { NextConfig } from "next";

const config: NextConfig = {
  // El backend corre aparte. En desarrollo se apunta a localhost:8100 y en
  // produccion a la URL de Railway, via NEXT_PUBLIC_API_URL.
  reactStrictMode: true,
};

export default config;
