// Loopback endpoint autopilot_notify.sh posts each outcome to. Bound to
// 127.0.0.1 only and guarded by a shared secret, so nothing off the machine
// can make the bot post.
import crypto from "node:crypto";
import http from "node:http";
import { isKnownOutcome, type AutopilotEvent } from "./announce.ts";
import { GAMEVER_RE } from "./repo.ts";

const MAX_BODY = 64 * 1024;

function authorised(header: string | undefined, secret: string): boolean {
    const given = Buffer.from(header ?? "");
    const wanted = Buffer.from(`Bearer ${secret}`);
    return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}

export function parseEvent(body: string): AutopilotEvent | null {
    let data: unknown;
    try {
        data = JSON.parse(body);
    } catch {
        return null;
    }
    if (typeof data !== "object" || data === null) return null;
    const { outcome, gamever, detail } = data as Record<string, unknown>;
    if (typeof outcome !== "string" || !isKnownOutcome(outcome)) return null;
    // "unknown": autopilot refused before it knew the build; admin channel only.
    if (typeof gamever !== "string" || !(GAMEVER_RE.test(gamever) || gamever === "unknown")) return null;
    return { outcome, gamever, detail: typeof detail === "string" ? detail : "", at: Date.now() };
}

export function startServer(port: number, secret: string, onEvent: (event: AutopilotEvent) => void): http.Server {
    const server = http.createServer((req, res) => {
        const reply = (status: number, text: string) => {
            res.writeHead(status, { "Content-Type": "text/plain" }).end(text);
        };
        if (req.method === "GET" && req.url === "/health") return reply(200, "ok");
        if (req.method !== "POST" || req.url !== "/event") return reply(404, "not found");
        if (!authorised(req.headers.authorization, secret)) return reply(401, "unauthorised");

        let size = 0;
        const chunks: Buffer[] = [];
        req.on("data", (chunk: Buffer) => {
            size += chunk.length;
            if (size > MAX_BODY) {
                reply(413, "too large");
                req.destroy();
                return;
            }
            chunks.push(chunk);
        });
        req.on("end", () => {
            if (res.headersSent) return;
            const event = parseEvent(Buffer.concat(chunks).toString("utf8"));
            if (!event) return reply(400, "bad event");
            onEvent(event);
            reply(202, "accepted");
        });
    });
    server.listen(port, "127.0.0.1");
    return server;
}
