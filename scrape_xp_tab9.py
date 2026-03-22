# --- DISCORD POSTER ---
def send_discord_post(title, date_label, ranking, team_total, post_type="daily"):
    print(f"📡 Posting {title} to Discord in separate, color-coded boxes...")
    if not ranking:
        return
    
    embeds_list = []
    #Emerald Green for Header/Footer, color-coded side bars for medals
    medal_colors = {0: 0xFFD700, 1: 0xC0C0C0, 2: 0xCD7F32}
    clr_main = 0x2ecc71
    
    embed_base_color = medal_colors.get(0, clr_main)
    max_gain = ranking[0]['gain']
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}

    # 1. HEADER BOX
    header_embed = {
        "title": f"🏆 {title} 🏆",
        "description": f"🗓️ Period: **{date_label}**",
        "color": embed_base_color
    }
    embeds_list.append(header_embed)

    # 2. STREAK LOGIC
    streak_footer_part = ""
    if post_type == "daily":
        streaks = load_json(STREAKS_PATH, {"daily": {"last_winner": "", "count": 0}})
        winner = ranking[0]['name']
        s_data = streaks.get("daily", {"last_winner": "", "count": 0})
        
        # Check if streak is broken
        if s_data["last_winner"] != "" and s_data["last_winner"] != winner:
            if s_data["count"] >= 2:
                # NEW RED EMBED FOR STREAK BREAKER
                embeds_list.append({
                    "title": "⚔️ STREAK BROKEN ⚔️",
                    "description": f"**{winner}** has just ended **{s_data['last_winner']}'s** `{s_data['count']}` day winning streak!",
                    "color": 0xFF0000 # CLR_RED
                })
            s_data["last_winner"] = winner
            s_data["count"] = 1
        else:
            s_data["last_winner"] = winner
            # Use get() to increment safely, preventing None errors
            s_data["count"] = s_data.get("count", 0) + 1
        
        save_json(STREAKS_PATH, streaks)
        # Winners specific streak for the footer
        s_icon = "👑" if s_data["count"] >= 5 else "🔥"
        streak_footer_part = f" | Winner Streak: {s_icon} {s_data['count']}"

    # 3. PLAYER CARDS (1st place is merged with the Header)
    for i, item in enumerate(ranking[:3]):
        name, gain, rank = item['name'], item['gain'], item.get('rank', '???')
        move = item.get('move', '⏺️')
        pct = int((gain / max_gain) * 100) if max_gain > 0 else 0
        move_str = f" ({move})" if move != "⏺️" else ""
        
        # Construct common base description (rank, XP, bar)
        base_desc = f"🌍 **World Rank: #{rank}**{move_str}\n`+{gain:,} XP` earned\n{make_bar(gain, max_gain)} `{pct}%`"

        # Construct author dictionary conditionally
        author_dict = {}
        if i == 0:
            # 1st place author is only the medal, name is moved to description
            author_dict = {"name": f"{medals[i]}"}
        else:
            # 2nd and 3rd place author is medal + name
            author_dict = {"name": f"{medals[i]} {name}"}

        # Build initial embed
        embed = {
            "author": author_dict,
            "color": medal_colors.get(i, embed_base_color)
        }
        
        # MERGE: If this is 1st place, build the header within the description
        if i == 0:
            # For 1st place, the header information is integrated into the description
            # We move the date to be above the winner name, so everything flows below the title.
            # Author becomes medal-only, Title is "Daily Champion", Description is "Date -> Winner -> Content"
            
            # The author field is above title and description, so it has to be medal-only for this request to work.
            embed["author"]["name"] = f"{medals[i]}"
            embed["title"] = f"🏆 {title} 🏆"
            embed["description"] = (
                f"🗓️ Period: **{date_label}**\n\n"
                f"🏆 **Winner: {name}**\n\n" # Move name here, make it bold
                f"{base_desc}"
            )
        else:
            # For 2nd and 3rd place, the name is in the author and the description is just content
            # The original code has "and date", but for 2nd/3rd place there is no title/date to flow below.
            # So, keep the name in the author field and just assign the content to description.
            embed["description"] = base_desc

        embeds_list.append(embed)

    # 4. OTHER GAINS & FOOTER
    others = [f"**{it['name']}** (+{it['gain']:,} XP)" for it in ranking[3:] if it['gain'] > 0]
    
    # Updated Footer with disclaimer and streak legend
    streak_legend = " | Streaks: 1-4 🔥 5+ 👑"
    footer_text = f"Total: {team_total:,} XP | World: {WORLD}{streak_footer_part}{streak_legend}\n⚠️ Only players in Top 1000 can be tracked"
    
    footer_embed = {
        "color": embed_base_color,
        "footer": {"text": footer_text}
    }
    
    if others:
        footer_embed["title"] = "--- Other Gains ---"
        footer_embed["description"] = "\n".join(others)
    else:
        footer_embed["description"] = "No other significant gains today."

    embeds_list.append(footer_embed)

    payload = {"embeds": embeds_list}
    r = requests.post(os.environ.get("DISCORD_WEBHOOK_URL"), json=payload)
    print(f"✅ Discord Status: {r.status_code}")
