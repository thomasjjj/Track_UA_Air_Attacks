# Ukrainian Air Force Attack Data Tracker
![image](https://github.com/user-attachments/assets/213b6f5e-e83d-4845-ac68-e0150ba7710b)


This tool automatically scrapes and analyzes overnight attack reports from the Ukrainian Air Force Telegram channel (@kpszsu) using OpenAI's GPT models to extract structured data about drone and missile attacks. It searches for messages containing "У ніч на" (overnight reports), processes them through OpenAI to identify attack types, numbers, and details, then saves the results to a CSV file for analysis. The scraper features interrupt-safe processing with resume capability, supports both fast direct search and reliable iteration methods, handles rate limiting, and can process unlimited messages or be configured for specific limits - making it ideal for researchers, analysts, and anyone tracking the ongoing conflict's aerial attack patterns over time.

![image](https://github.com/user-attachments/assets/46457074-1f83-4626-a38e-3604406ecf9a)
Example sheet with the data. The OpenAI column is the JSON results (needs unpacking)
