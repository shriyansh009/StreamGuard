"""Seed dataset and utilities for training Meta FastText content moderation models."""

from typing import List, Tuple

# Comprehensive labeled dataset for supervised multi-label FastText model training.
# Each entry is a tuple of (label_str, message_text).
# If multiple labels apply, separate them with spaces (e.g. "threat profanity").
SEED_MODERATION_DATA: List[Tuple[str, str]] = [
    # -------------------------------------------------------------------------
    # Clean / Benign Messages (Label: clean, Severity: 0.0)
    # -------------------------------------------------------------------------
    ("clean", "Hello everyone, hope you are having a wonderful stream!"),
    ("clean", "Good morning chat! How is everyone doing today?"),
    ("clean", "Nice play, that was totally awesome gg wp!"),
    ("clean", "Thanks for the great stream, really love your content."),
    ("clean", "Welcome to the channel everyone! Enjoy the show."),
    ("clean", "What game are we going to play next?"),
    ("clean", "That was a really great round, good clutch!"),
    ("clean", "Good luck with the tournament today! You got this!"),
    ("clean", "Can you show your graphics settings and keybinds please?"),
    ("clean", "Have a nice day everyone in chat!"),
    ("clean", "This stream is always so fun and chill to watch."),
    ("clean", "Great job on that victory, well deserved!"),
    ("clean", "Hello world, happy to be here with you all."),
    ("clean", "Hi streamer! First time chatting here."),
    ("clean", "Let's go team, amazing teamwork!"),
    ("clean", "That soundtrack is incredible, what song is this?"),
    ("clean", "What coffee are you drinking today?"),
    ("clean", "The graphics on this new game look stunning."),
    ("clean", "I really appreciate your daily stream schedule."),
    ("clean", "Hahaha that was hilarious when that glitch happened!"),
    ("clean", "GG guys, see you in the next stream tomorrow."),
    ("clean", "Can someone explain the rules of this challenge?"),
    ("clean", "I love how positive this community is."),
    ("clean", "Awesome strategy! I never thought of flanking there."),
    ("clean", "Hope you take time to rest after this marathon."),
    ("clean", "What microphone and camera setup are you using?"),
    ("clean", "Good evening from Australia!"),
    ("clean", "Thank you for answering my question earlier."),
    ("clean", "That was close! Heart was racing watching that."),
    ("clean", "Best streamer on Twitch / YouTube hands down!"),
    ("clean", "Nice one! That headshot was crazy clean."),
    ("clean", "Looking forward to tomorrow's stream."),
    ("clean", "Have fun everyone and stay hydrated!"),

    # -------------------------------------------------------------------------
    # Threats (Label: threat, Severity: 0.95)
    # -------------------------------------------------------------------------
    ("threat", "I will kill you right now"),
    ("threat", "I will kill you"),
    ("threat", "I'll kill you when I find you"),
    ("threat", "I will murder you and your whole family"),
    ("threat", "I will slaughter you in cold blood"),
    ("threat", "I will shoot you if you say that again"),
    ("threat", "I will strangle you until you stop breathing"),
    ("threat", "Go die and kys"),
    ("threat", "kill yourself right now, nobody wants you"),
    ("threat", "commit suicide and go die"),
    ("threat", "kys you piece of garbage"),
    ("threat", "I'll stab you if you come here"),
    ("threat", "I will stab you in the chest"),
    ("threat", "Hope you die in a fire"),
    ("threat", "hope you die and burn in hell"),
    ("threat", "hope you get cancer and die slowly"),
    ("threat", "I will bomb your house tomorrow"),
    ("threat", "blow up your house and your school"),
    ("threat", "burn down your house with you inside"),
    ("threat", "bomb the school and the entire building"),
    ("threat", "put a bullet in you and your head"),
    ("threat", "slit your throat while you sleep"),
    ("threat", "I will hunt you down and kill you"),
    ("threat", "die die die kill yourself"),
    ("threat", "I'm going to put a bullet in your head"),
    ("threat", "you will be murdered tonight"),
    ("threat", "slit your throat right now"),

    # -------------------------------------------------------------------------
    # Hate Speech (Label: hate_speech, Severity: 0.90)
    # -------------------------------------------------------------------------
    ("hate_speech", "gas the jews right now"),
    ("hate_speech", "gas the jews"),
    ("hate_speech", "white power heil hitler"),
    ("hate_speech", "heil hitler and white supremacy"),
    ("hate_speech", "kill all muslims today"),
    ("hate_speech", "kill all blacks and all jews"),
    ("hate_speech", "kill all whites and gays"),
    ("hate_speech", "subhuman race of parasites"),
    ("hate_speech", "parasites and vermin race of people"),
    ("hate_speech", "subhuman vermin should be exterminated"),
    ("hate_speech", "you dirty nigger"),
    ("hate_speech", "fucking niggers everywhere"),
    ("hate_speech", "stupid faggot get off the stream"),
    ("hate_speech", "all faggots must die"),
    ("hate_speech", "kike spic chink wetback"),
    ("hate_speech", "dirty chink go back to your country"),
    ("hate_speech", "tranny shemale he-she disgusting"),
    ("hate_speech", "trannies are sick perverts"),
    ("hate_speech", "white power kill them all"),
    ("hate_speech", "subhuman ethnicity of vermin"),
    ("hate_speech", "gas them all in the ovens"),
    ("hate_speech", "heil hitler death to minorities"),

    # -------------------------------------------------------------------------
    # Profanity (Label: profanity, Severity: 0.70)
    # -------------------------------------------------------------------------
    ("profanity", "What the fucking hell is this?"),
    ("profanity", "You are a total asshole"),
    ("profanity", "Get this piece of shit out of here"),
    ("profanity", "fuck you and your fucking team"),
    ("profanity", "what the fuck is wrong with this game"),
    ("profanity", "you piece of shit motherfucker"),
    ("profanity", "cocksucker whore slut bastard"),
    ("profanity", "shut up cunt"),
    ("profanity", "total dickhead and asshole"),
    ("profanity", "fucking bullcrap and bullshit"),
    ("profanity", "whore slut bastard motherfucker"),
    ("profanity", "holy shit what the fuck"),
    ("profanity", "eat shit and choke on a dick"),
    ("profanity", "you suck dickhead"),
    ("profanity", "fucking hell this is garbage"),

    # -------------------------------------------------------------------------
    # Harassment (Label: harassment, Severity: 0.60)
    # -------------------------------------------------------------------------
    ("harassment", "You are so ugly and pathetic"),
    ("harassment", "Nobody likes you, waste of life"),
    ("harassment", "I will doxx your address and leak your photos"),
    ("harassment", "Get lost loser"),
    ("harassment", "you are so fat and worthless"),
    ("harassment", "everyone hates you, waste of breath and space"),
    ("harassment", "nobody loves you, you stupid disgusting idiot"),
    ("harassment", "i will leak your ip and your home location"),
    ("harassment", "i will doxx you and post your nudes"),
    ("harassment", "get lost loser nobody wants you here"),
    ("harassment", "stfu get lost you pathetic loser"),
    ("harassment", "you are completely useless and stupid"),
    ("harassment", "you are disgusting and repulsive"),
    ("harassment", "waste of space stop streaming"),
    ("harassment", "shut up idiot you are trash"),

    # -------------------------------------------------------------------------
    # Spam (Label: spam, Severity: 0.40)
    # -------------------------------------------------------------------------
    ("spam", "Wooooooow this is insane!!!!!"),
    ("spam", "aaaaaaa bbbbbbb ccccccc !!!!!!!!"),
    ("spam", "CHECKOUTTHISLINK RIGHTNOW"),
    ("spam", "CLICKHERE RIGHTNOW BUYCHEAP"),
    ("spam", "FREE CRYPTO CLICK HERE TO CLAIM"),
    ("spam", "free crypto click here to claim guaranteed profit"),
    ("spam", "dm for crypto signals guaranteed profit everyday"),
    ("spam", "click here to claim free coins guaranteed profit"),
    ("spam", "promo promo promo promo"),
    ("spam", "buy buy buy buy buy now"),
    ("spam", "spam spam spam spam"),
    ("spam", "click http://scam.link or t.me/freecrypto"),
    ("spam", "join discord.gg/freebies or whatsapp +1234567890"),
    ("spam", "t.me/freecrypto signals dm now"),
    ("spam", "free robux free vbucks click http://free.gift"),
    ("spam", "CHECKTHISOUT NOWWWWWWWW"),

    # -------------------------------------------------------------------------
    # Multi-label / Mixed Violations
    # -------------------------------------------------------------------------
    ("threat profanity", "I will kill you, you fucking idiot"),
    ("threat profanity", "I will murder you, you fucking asshole"),
    ("threat profanity", "I will shoot you in the fucking face"),
    ("threat harassment", "I will kill you, you pathetic loser"),
    ("threat harassment", "Nobody likes you, go die and kys"),
    ("profanity harassment", "Shut up, bitch"),
    ("profanity harassment", "Shut the fuck up, bitch"),
    ("profanity harassment", "fucking bitch asshole get lost"),
    ("hate_speech threat", "kill all muslims today and gas the jews"),
    ("hate_speech profanity", "fucking nigger piece of shit"),
    ("hate_speech harassment", "you disgusting subhuman vermin, get lost loser"),
]
