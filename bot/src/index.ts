import "dotenv/config";
import { Telegraf } from "telegraf";

declare const process: {
  env: Record<string, string | undefined>;
  exit(code?: number): never;
  once(event: "SIGINT" | "SIGTERM", listener: () => void): void;
};

const token = process.env.BOT_TOKEN?.trim();

if (!token) {
  console.error("Укажи BOT_TOKEN в файле .env.");
  process.exit(1);
}

const bot = new Telegraf(token);

const helloText = "привет";

bot.start((ctx) => {
  return ctx.reply("Привет! Я базовый бот. Напиши мне любое сообщение.");
});

bot.help((ctx) => {
  return ctx.reply("Я отвечаю на текстовые сообщения. Попробуй написать: привет");
});

bot.on("text", (ctx) => {
  const text = ctx.message.text.trim().toLowerCase();

  if (text === helloText || text === "hello") {
    return ctx.reply("Привет! Рад тебя видеть.");
  }

  return ctx.reply(`Ты написал: ${ctx.message.text}`);
});

bot.on("message", (ctx) => {
  return ctx.reply("Пока я умею отвечать только на текстовые сообщения.");
});

bot.catch((error) => {
  console.error("Bot error:", error);
});

bot
  .launch()
  .then(() => {
    console.log("Bot started");
  })
  .catch((error: unknown) => {
    const code =
      error instanceof Error && "code" in error
        ? String(error.code)
        : "UNKNOWN";

    if (code === "ETIMEDOUT" || code === "EACCES" || code === "ECONNRESET") {
      console.error(
        `Не удалось подключиться к Telegram API (${code}). Проверь интернет, VPN/прокси и доступ к api.telegram.org.`,
      );
      process.exit(1);
    }

    const message = error instanceof Error ? error.message : String(error);

    console.error(`Не удалось запустить бота: ${message}`);
    process.exit(1);
  });

process.once("SIGINT", () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));
