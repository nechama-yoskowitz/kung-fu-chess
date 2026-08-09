# Server Design – Kung-Fu Chess

## 1. מטרת המסמך

מטרת המסמך היא להציע Design לצד השרת של **Kung-Fu Chess** כך שיוכל לגדול ממימוש נוכחי של שרת יחיד למערכת מבוזרת שיכולה לתמוך במספר גדול מאוד של משתמשים ומשחקים פעילים.

הדרישות שנלקחו בחשבון הן:

* תמיכה ב־**100 מיליון משתמשים רשומים**.
* תמיכה ב־**10 מיליון משתמשים פעילים בו־זמנית** מכל העולם.
* כל משתמש פעיל מבצע בממוצע **צעד אחד בכל שתי שניות**.
* משחק ממוצע נמשך **30–90 שניות**.
* כל משתמש צריך להיות מסוגל לשחק עם כל משתמש אחר ולהיכנס לכל Room, גם כאשר השחקנים מחוברים לשרתים שונים.
* המערכת צריכה להיות מסוגלת לגדול אופקית באמצעות מספר רב של Docker containers.
* יש לתכנן את חלוקת האחריות בין סוגי השרתים השונים ואת הדרך שבה מתבצע routing של משתמשים ומשחקים.

ה־Design המוצע אינו רק Design של מחלקות, אלא Design של מערכת שרתים מבוזרת. כלומר, המטרה היא להחליט אילו רכיבים צריכים להיות משותפים לכל השרתים, אילו נתונים ניתן לשמור מקומית, כיצד מחלקים עומס בין שרתים, וכיצד מונעים מצב שבו מידע חשוב קיים רק בתוך process יחיד.

---

## 2. המצב הנוכחי של השרת

במימוש הנוכחי קיים שרת WebSocket יחיד.

`GameWebSocketServer` מחזיק ומפעיל בתוך אותו process מספר רכיבים מרכזיים:

* `ClientSessionRouter`
* `GameSessionManager`
* `RoomManager`
* `MatchmakingService`
* `ReconnectManager`
* שירותי authentication ו־rating
* מספר `GameSession`-ים פעילים

בנוסף, המשתמשים וה־ratings נשמרים כיום ב־SQLite דרך `UserRepository`.

המבנה הנוכחי מתאים מאוד לשלב שבו יש שרת יחיד, משום שכל הרכיבים יכולים לגשת ישירות לאותו זיכרון.

לדוגמה, כאשר `RoomManager` יוצר Room, ה־Room קיים בזיכרון של אותו process. כאשר `MatchmakingService` מוסיף שחקן לתור, התור נמצא גם הוא בזיכרון של אותו process. כאשר `GameSessionManager` יוצר משחק, ה־`GameSession` קיים בתוך אותו שרת.

הבעיה מתחילה כאשר מריצים מספר עותקים של השרת.

אם נריץ לדוגמה שלושה containers:

```text
Server A
Server B
Server C
```

לכל אחד מהם יהיה זיכרון נפרד.

לכן Room שנוצר ב־Server A לא יהיה מוכר אוטומטית ל־Server B, ושחקן שמחכה ל־matchmaking ב־Server B לא יהיה מוכר ל־Server C.

מכאן שהמעבר ל־Scale מחייב להפריד בין:

1. **מידע מקומי של Game Server מסוים**.
2. **מידע משותף שכל המערכת צריכה להכיר**.
3. **מידע קבוע שצריך להישמר גם אחרי restart**, כמו משתמשים ו־ratings.

---

# 3. הנחות עומס

## 3.1 משתמשים רשומים

המערכת צריכה לתמוך ב:

```text
100,000,000 registered users
```

לא כל המשתמשים האלה מחוברים בו־זמנית. זהו בעיקר עומס על שכבת האחסון הקבועה, כלומר על בסיס הנתונים של המשתמשים.

---

## 3.2 משתמשים פעילים בו־זמנית

בכל רגע משחקים:

```text
10,000,000 concurrent players
```

משחק מכיל שני שחקנים, לכן במקרה שבו כל המשתמשים נמצאים במשחק:

```text
10,000,000 / 2 = 5,000,000 concurrent games
```

כלומר המערכת צריכה להיות מסוגלת להחזיק בסדר גודל של **5 מיליון Game Sessions פעילות בו־זמנית**.

זה לא אומר שנפעיל Docker נפרד לכל משחק. Game Server אחד יכול להחזיק מספר רב של משחקים במקביל, והמספר המדויק ייקבע לפי benchmark של CPU, זיכרון וכמות חיבורי WebSocket שכל instance מסוגל להחזיק.

---

## 3.3 מספר צעדים בשנייה

כל משתמש מבצע בממוצע צעד בכל שתי שניות.

לכן:

```text
10,000,000 players / 2 seconds
= 5,000,000 moves per second
```

המערכת צריכה להתמודד בממוצע עם כ־**5 מיליון move requests בשנייה**.

מכיוון שבמשחק יש שני שחקנים, כל משחק מייצר בממוצע בערך צעד אחד בשנייה:

```text
2 players × 0.5 moves/sec = 1 move/sec per game
```

---

## 3.4 קצב יצירה וסיום של משחקים

יש כ־5 מיליון משחקים פעילים בו־זמנית.

אם ניקח זמן משחק ממוצע של כ־60 שניות, כדי לשמור על מספר קבוע של 5 מיליון משחקים פעילים צריכים להסתיים ולהתחיל בערך:

```text
5,000,000 / 60
≈ 83,333 games per second
```

אם המשחקים קרובים יותר ל־30 שניות, ה־churn יכול להגיע לכ־166,000 משחקים בשנייה.

אם המשחקים קרובים יותר ל־90 שניות, מדובר בכ־55,000 משחקים בשנייה.

מכאן ששכבת ה־matchmaking והקצאת ה־Game Servers צריכה להיות יעילה מאוד, משום שמשחקים נוצרים ונמחקים בקצב גבוה.

---

# 4. בחירת Database

## 4.1 האם SQLite מתאים?

SQLite מתאים מאוד לפרויקט מקומי, לטסטים ולשרת קטן, אך אינו מתאים כבסיס הנתונים המרכזי של המערכת המתוארת.

במימוש הנוכחי בסיס הנתונים הוא קובץ מקומי:

```text
kungfu_chess.db
```

כאשר יש שרת יחיד, זה פשוט ונוח.

כאשר יש אלפי containers, לא ניתן לתת לכל container קובץ SQLite משלו, משום שכל container היה מקבל עותק אחר של הנתונים.

לדוגמה:

```text
Game Server A -> local SQLite A
Game Server B -> local SQLite B
Game Server C -> local SQLite C
```

אם משתמש נרשם דרך Server A ולאחר מכן מתחבר דרך Server C, Server C עלול לא להכיר אותו כלל.

גם שיתוף של אותו קובץ SQLite בין אלפי שרתים אינו פתרון מתאים. SQLite הוא database מבוסס קובץ ואינו נועד להיות database server מרכזי עם כמות עצומה של clients שכותבים במקביל.

לכן במערכת המבוזרת **SQLite לא ישמש כ־production database**.

אפשר עדיין להשאיר אותו לטסטים מקומיים או ל־development.

---

## 4.2 ה־Database המוצע: PostgreSQL

לנתונים הקבועים הייתי משתמשת ב־**PostgreSQL**.

הנתונים הקבועים כוללים לדוגמה:

* User ID
* Username
* Password hash
* Rating
* מידע בסיסי על חשבון
* תוצאות משחקים, אם נרצה לשמור history
* מידע נוסף שצריך לשרוד restart של שרת

היתרונות המרכזיים של PostgreSQL עבור המערכת:

* הוא database מסוג client/server, ולכן מספר רב של services יכולים לגשת אליו.
* הוא תומך ב־transactions, שחשובים לדוגמה בעדכון rating של שני שחקנים.
* הוא מתאים לכמויות נתונים גדולות בהרבה מה־SQLite המקומי.
* ניתן להוסיף indexes לפי אופן השימוש.
* ניתן להשתמש ב־read replicas במקרה שיש עומס גבוה של קריאות.
* כאשר המערכת גדלה עוד יותר, ניתן לבצע partitioning או sharding לפי User ID.

100 מיליון משתמשים אינם סיבה בפני עצמה לבחור NoSQL. הנתונים של משתמש, authentication ו־rating הם נתונים מובנים מאוד, ויש חשיבות ל־consistency. לכן relational database הוא בחירה טבעית.

בשלב ראשון ניתן להתחיל עם PostgreSQL cluster מרכזי, ובהמשך לבצע partitioning/sharding אם benchmark אמיתי מראה שהוא נדרש.

---

# 5. חלוקת המערכת לשירותים

במקום שכל Docker יריץ את כל האחריות של המערכת, אני מציעה להפריד את צד השרת למספר סוגי services.

```text
                         Internet
                            |
                            v
                  Global Load Balancer
                            |
                            v
                 WebSocket / Gateway Layer
                            |
          +-----------------+------------------+
          |                 |                  |
          v                 v                  v
       Auth             Matchmaking        Room Router
          |                 |                  |
          |                 |                  v
          |                 |           Game Server Pool
          |                 |          /       |        \
          |                 |       Server A Server B Server C
          |                 |
          +---------> PostgreSQL
                            ^
                            |
                      Shared Redis
```

החלוקה הלוגית היא:

### 1. Gateway / Connection Service

אחראי על:

* קבלת חיבורי WebSocket מהלקוחות.
* שמירה על החיבור עצמו.
* authentication token validation.
* קבלת הודעות מהלקוח.
* routing של הודעת משחק ל־Game Server שמחזיק את ה־Room.
* החזרת הודעות מהמערכת ללקוח.

ה־Gateway צריך להיות יחסית stateless מבחינת game state.

כלומר, הוא לא אמור להחזיק את לוח המשחק עצמו. אם Gateway נופל, ה־Game Session לא אמור להיעלם יחד איתו.

---

### 2. Authentication / User Service

אחראי על:

* register
* login
* שליפת פרטי משתמש
* גישה ל־PostgreSQL
* authentication

כך Game Servers לא צריכים לבצע בעצמם authentication מול בסיס הנתונים.

---

### 3. Matchmaking Service

בשרת הנוכחי `MatchmakingService` שומר queue מקומי בזיכרון.

במערכת מרובת שרתים זה לא יכול להישאר local, משום ששחקן שמחכה ב־Server A צריך להיות מסוגל לקבל match מול שחקן שהתחבר ל־Server B.

לכן ה־matchmaking צריך להיות שירות משותף.

ניתן לשמור את התור ב־Redis או במנגנון distributed queue אחר.

לדוגמה:

```text
Player A -> Gateway 1 --\
                         -> Shared Matchmaking Queue
Player B -> Gateway 8 --/
```

ה־Matchmaking Service מוצא זוג מתאים, יוצר Room ID, בוחר Game Server פנוי, ורושם את המיפוי:

```text
room_id -> game_server_id
```

---

### 4. Room Directory / Routing Service

זהו אחד הרכיבים החשובים ביותר ב־Design.

כאשר יש הרבה Game Servers, חייבים לדעת באיזה שרת נמצא כל Room.

לכן נשמור registry משותף בסגנון:

```text
room:98121 -> game-server-17
room:98122 -> game-server-42
room:98123 -> game-server-17
```

אפשר לשמור מידע כזה ב־Redis, משום שזה מידע זמני, קטן יחסית, ונדרש לגישה מהירה מאוד.

כאשר שחקן שולח:

```text
JOIN_ROOM 98122
```

המערכת מבצעת:

```text
Room Directory:
98122 -> game-server-42
```

ומנתבת את השחקן ל־Game Server 42.

כך **כל שחקן יכול להצטרף לכל Room**, ללא קשר ל־Gateway שאליו התחבר בתחילת החיבור.

---

### 5. Game Server

Game Server אחראי על ה־state החי של המשחקים שהוקצו אליו.

בתוכו ימשיכו לחיות הרעיונות שכבר קיימים בפרויקט:

* `GameSession`
* `GameEngine`
* board state
* active moves
* game clock
* collision resolution
* jump state
* cooldowns
* game-over detection

כל Room מוקצה ל־Game Server יחיד בזמן נתון.

זה חשוב מאוד משום שה־Game Engine הוא stateful.

לדוגמה:

```text
Room 98122
Players: Alice, Bob
Game state: ...
Current clock: ...
Active moves: ...
```

אם move אחד יעובד ב־Server A וה־move הבא ב־Server B ללא shared authoritative state, השרתים עלולים לחשב מצבי משחק שונים.

לכן אני בוחרת ב־**single authoritative Game Server per Room**.

כל הצעדים של אותו Room מגיעים לאותו Game Server.

Game Server אחד יכול כמובן להחזיק הרבה Rooms במקביל.

---

### 6. Rating / Result Service

בסיום משחק אין צורך שכל Game Server יבצע בעצמו לוגיקה מורכבת מול בסיס הנתונים.

הוא יכול לייצר Game Result:

```text
game_id
winner
loser
result
timestamp
```

ולשלוח אותו ל־Rating Service.

ה־Rating Service מעדכן את שני המשתמשים בצורה transactionally ב־PostgreSQL.

כך ה־Game Server יכול להשתחרר מהר מה־Game Session שסיים את חייו.

---

# 6. Stateless לעומת Stateful

זוהי הבחנה מרכזית ב־Design.

## Stateless Services

רכיב stateless אינו מחזיק בזיכרון מקומי מידע שהוא המקור היחיד לאמת.

לדוגמה:

* Auth Service
* API services
* חלק גדול מ־Gateway logic

ניתן להוסיף או להסיר instances שלהם בקלות יחסית.

אם instance אחד נופל, request חדש יכול להגיע ל־instance אחר.

---

## Stateful Services

Game Server הוא stateful בזמן שמשחק פעיל, משום שהוא מחזיק את מצב המשחק.

לכן לא ניתן לנתב כל message ל־Game Server אקראי.

צריך לשמור mapping:

```text
room_id -> game_server_id
```

ולנתב את כל הודעות המשחק לאותו server.

זה למעשה הפתרון לשאלה:

> אם יש כמה שרתים, איך יודעים איזה שחקנים נמצאים על איזה שרת?

אין צורך ששחקן "יהיה שייך" לנצח לשרת אחד.

מה שחשוב הוא לדעת:

```text
player_id -> current_room_id
room_id   -> game_server_id
```

המיפויים האלה נשמרים ב־shared fast store.

---

# 7. Redis והמידע הזמני המשותף

אני מציעה להשתמש ב־Redis עבור מידע זמני ומהיר, ולא כתחליף מלא ל־PostgreSQL.

דוגמאות למידע שמתאים ל־Redis:

```text
player_id -> room_id
room_id -> game_server_id
matchmaking queues
active connection location
temporary reconnect information
server capacity counters
```

המידע הזה משתנה מהר ואינו בהכרח צריך להישמר לנצח.

PostgreSQL לעומת זאת הוא ה־source of truth של המידע הקבוע:

```text
users
password hashes
ratings
game history (if required)
```

כך נוצרת הפרדה ברורה:

```text
PostgreSQL = persistent data
Redis      = fast shared ephemeral data
GameServer = live game state
```

---

# 8. איך "כולם יכולים לשחק עם כולם"

נניח ש־Player A מחובר ל־Gateway באירופה ו־Player B מחובר ל־Gateway אחר.

הם לא חייבים להיות מחוברים לאותו Gateway.

תהליך matchmaking יכול להיות:

```text
1. Player A joins matchmaking.
2. Gateway A adds A to shared matchmaking queue.
3. Player B joins matchmaking.
4. Gateway B adds B to the same shared queue.
5. Matchmaking Service matches A and B.
6. Scheduler selects Game Server 37.
7. New Room 81234 is created on Game Server 37.
8. Redis stores:
      room:81234 -> game-server-37
      player:A   -> room:81234
      player:B   -> room:81234
9. Both Gateways route game messages to Game Server 37.
```

לכן העובדה שהשחקנים התחברו פיזית לשרתים שונים אינה מונעת מהם לשחק ביחד.

---

# 9. איך כל משתמש יכול להיכנס לכל Room

נניח ש־Room 81234 כבר נמצא ב־Game Server 37.

שחקן חדש מבקש:

```text
JOIN_ROOM 81234
```

ה־Gateway לא מחפש את החדר בזיכרון המקומי שלו.

במקום זאת:

```text
Gateway
   |
   v
Room Directory / Redis
   |
   +--> room:81234 = game-server-37
   |
   v
Game Server 37
```

ה־Gateway שולח את בקשת ההצטרפות ל־Game Server שמחזיק את החדר.

ה־Game Server עצמו הוא זה שבודק אם מותר להצטרף, אם יש מקום, ואם מצב החדר מאפשר זאת.

כך `RoomManager` אינו יכול עוד להיות registry גלובלי שקיים רק בזיכרון של server יחיד. חלק מהאחריות שלו צריך להפוך ל־distributed room directory.

---

# 10. Network Traffic

הדרישה אומרת שכל משתמש שולח בממוצע move אחד בכל שתי שניות.

כבר חישבנו:

```text
5,000,000 move requests / second
```

כדי לחשב נפח תעבורה צריך להניח גודל ממוצע של הודעה.

נניח לצורך estimate שהודעת move לאחר serialization היא בערך 100 bytes בממוצע.

לדוגמה, היא יכולה להכיל:

```json
{
  "type": "move_request",
  "room_id": 81234,
  "from": [7, 3],
  "to": [5, 3]
}
```

אז תעבורת ה־application payload הנכנסת היא בערך:

```text
5,000,000 × 100 bytes
= 500,000,000 bytes/sec
≈ 500 MB/sec
≈ 4 Gbit/sec
```

זה רק traffic נכנס של move requests.

כל move צריך בדרך כלל גם לגרום לעדכון לצד השני, ולעיתים ליותר מהודעה אחת:

* move accepted
* game state update
* collision event
* captured piece
* cooldown / state change
* game ended

לכן בפועל תהיה גם תעבורה יוצאת משמעותית.

בנוסף קיימת תקורה של:

* WebSocket framing
* TCP/IP
* TLS
* heartbeats
* authentication
* matchmaking
* reconnects

לכן בפועל צריך לתכנן לסדר גודל גדול יותר מ־4 Gbit/sec.

עם זאת, הנקודה החשובה היא שהעומס **מחולק בין הרבה שרתים ואזורים**, ולא עובר דרך NIC יחיד של שרת אחד.

4–10+ Gbit/sec עבור מערכת גלובלית גדולה אינו מספר חריג כשמחלקים אותו בין data centers ו־server instances רבים, אבל הוא עומס בלתי סביר עבור שרת application יחיד.

---

# 11. משמעות משך משחק של 30–90 שניות

העובדה שמשחק קצר יחסית משפיעה משמעותית על הארכיטקטורה.

`GameSession` הוא אובייקט קצר־חיים:

```text
Create
  |
  v
Active for 30–90 seconds
  |
  v
Game ends
  |
  v
Persist final result
  |
  v
Release memory
```

כלומר, Game Servers צריכים להיות מותאמים ל־high churn:

* יצירה מהירה של Game Sessions.
* מחיקה מהירה של Sessions שהסתיימו.
* reuse של אותו Docker להרבה משחקים בזה אחר זה.
* אין צורך ליצור Docker חדש לכל משחק.
* Docker של Game Server נשאר חי ומארח הרבה משחקים קצרים לאורך זמן.

זו הבחנה חשובה:

```text
Docker lifetime != GameSession lifetime
```

Game Server container יכול לחיות שעות או ימים.

בתוכו יכולים לעבור אלפי או מיליוני Game Sessions לאורך חייו, כאשר כל session חי רק 30–90 שניות.

---

# 12. חלוקת משחקים בין Game Servers

כל Game Server מפרסם מידע בסיסי על ה־capacity שלו.

לדוגמה:

```text
game-server-1 : 4,200 active rooms
game-server-2 : 2,300 active rooms
game-server-3 : 4,900 active rooms
```

כאשר נוצר match חדש, scheduler בוחר server לפי אחד מהקריטריונים:

* מספר active games.
* CPU usage.
* memory usage.
* מספר WebSocket connections.
* region.
* latency של שני השחקנים.

בגרסה פשוטה אפשר לבחור server עם מספר המשחקים הנמוך ביותר.

בגרסה מתקדמת יותר אפשר לתת ל־Kubernetes לבצע scaling של מספר ה־Game Server Pods לפי metrics.

---

# 13. Docker

כל service ירוץ בתוך Docker image משלו.

לדוגמה:

```text
kungfu-gateway
kungfu-auth
kungfu-matchmaking
kungfu-game-server
kungfu-rating
```

אפשר גם להתחיל בפחות images ולפצל רק את השירותים המרכזיים.

היתרון של Docker הוא שכל instance מקבל אותה סביבת הרצה:

* אותה גרסת Python.
* אותן dependencies.
* אותו source code version.
* אותה command להרצה.

כך אפשר להפעיל מספר רב של copies מאותו image בצורה עקבית.

---

# 14. Kubernetes / K3s

Docker פותר את בעיית האריזה וההרצה של container בודד.

אבל כאשר יש מאות או אלפי instances צריך מערכת שמנהלת אותם.

לשם כך ניתן להשתמש ב־Kubernetes.

Kubernetes יהיה אחראי על:

* יצירת Pods.
* שמירה על מספר replicas רצוי.
* restart ל־Pods שנפלו.
* service discovery.
* networking פנימי בין services.
* load balancing פנימי.
* rolling deployments.
* scaling של מספר instances.

לסביבת development, demo או cluster קטן ניתן להשתמש ב־K3s, שהוא distribution קל יותר של Kubernetes.

כלומר:

```text
Docker     -> packages and runs containers
Kubernetes -> orchestrates many containers
K3s        -> lightweight Kubernetes distribution
```

---

# 15. Global Distribution

הדרישה אומרת שהשחקנים מגיעים מכל העולם.

לכן במערכת אמיתית לא הייתי מריצה את כל Game Servers ב־data center אחד.

עדיף לחלק את המערכת למספר regions:

```text
Europe
US
Asia
```

שחקן יתחבר בדרך כלל ל־region הקרוב אליו כדי להקטין latency.

ב־matchmaking של שני שחקנים מאזורים שונים צריך לבחור region שמספק פשרה סבירה עבור שניהם.

במשחק realtime latency חשובה מאוד, ולכן geographic placement של Game Server משמעותי יותר מאשר בשירות HTTP רגיל.

מידע קבוע כמו user account יכול להיות נגיש מכל region, בעוד שה־live game צריך להיות ממוקם באזור שנבחר למשחק.

---

# 16. Failure Handling

במערכת עם אלפי instances צריך להניח ששרתים ייפלו מדי פעם.

## Gateway failure

אם Gateway נופל, הלקוח יכול להתחבר מחדש.

מכיוון שה־Room mapping נמצא ב־shared store, Gateway חדש יכול למצוא:

```text
player_id -> room_id
room_id -> game_server_id
```

ולחבר את המשתמש חזרה למשחק.

ה־`ReconnectManager` הנוכחי יכול לשמש בסיס לרעיון הזה, אך המידע שהוא מחזיק לא יכול להישאר רק בזיכרון של process יחיד.

---

## Game Server failure

זו בעיה קשה יותר משום ש־Game Server מחזיק live state.

יש כמה רמות פתרון אפשריות:

### פתרון בסיסי

אם Game Server נופל, המשחקים שעליו מסתיימים או מוכרזים כ־aborted.

זה פשוט אך פוגע בחוויית המשתמש.

### פתרון מתקדם

ניתן לשמור snapshots תקופתיים או event log של המשחק בשירות חיצוני.

במקרה של failure:

1. Kubernetes מעלה Game Server חדש.
2. המערכת טוענת snapshot אחרון.
3. משחזרת events מאז ה־snapshot.
4. מעדכנת:
   `room_id -> new_game_server_id`.
5. השחקנים מתחברים מחדש.

לפרויקט הנוכחי הייתי מתחילה מהפתרון הבסיסי או מ־periodic snapshots, ולא בונה replication מלא של כל GameSession לפני שיש צורך אמיתי.

---

# 17. Consistency

למשחק עצמו נדרש authoritative ordering.

שני שחקנים עלולים לשלוח moves כמעט באותו רגע.

לכן אותו Room צריך להיות מעובד על ידי Game Server אחד, שמחזיק סדר אירועים ברור ומשתמש ב־Game Engine הקיים כדי לפתור collisions, movement timing ו־game state.

כך נמנעת בעיה שבה שני servers שונים מאשרים במקביל שתי גרסאות שונות של אותו board.

לנתוני משתמש ו־rating נעדיף consistency חזקה דרך transaction ב־PostgreSQL.

לנתונים זמניים כמו server load או presence ניתן לקבל לעיתים eventual consistency קצרה.

---

# 18. Scaling Strategy

המערכת תשתמש בעיקר ב־Horizontal Scaling.

במקום לנסות לבנות שרת אחד חזק מאוד:

```text
One huge server
```

מריצים הרבה instances:

```text
Gateway x N
Auth x N
Matchmaking x N
GameServer x N
Rating x N
```

Kubernetes יכול להגדיל או להקטין את מספר ה־replicas בהתאם לעומס.

לדוגמה:

```text
low load:
50 Game Server Pods

high load:
500 Game Server Pods
```

המספרים עצמם אינם קבועים מראש.

צריך benchmark כדי למדוד כמה concurrent connections וכמה Game Sessions instance אחד מסוגל לשרת תוך שמירה על latency תקין.

רק לאחר המדידה ניתן לחשב בצורה טובה כמה Pods נדרשים ל־10 מיליון שחקנים.

---

# 19. Monitoring

במערכת כזאת לא מספיק לדעת ש־process "רץ".

צריך למדוד לפחות:

* number of connected users
* number of active rooms
* active games per Game Server
* moves per second
* average move processing latency
* WebSocket disconnect rate
* matchmaking queue length
* matchmaking waiting time
* CPU usage
* memory usage
* network throughput
* DB latency
* Redis latency
* error rate

Metrics כאלה יאפשרו גם לקבוע thresholds ל־autoscaling.

---

# 20. Flow מלא של משחק

להלן flow אפשרי מקצה לקצה.

```text
1. Client connects to closest Gateway.

2. Client logs in.

3. Gateway/Auth Service verifies credentials using PostgreSQL.

4. Client requests matchmaking.

5. Player is inserted into shared Matchmaking Queue.

6. Matchmaking Service finds another player.

7. Scheduler chooses a Game Server with available capacity
   and preferably acceptable geographic latency.

8. Game Server creates a new GameSession.

9. Shared Room Directory stores:
      room_id -> game_server_id

10. Player directory stores:
      player_a -> room_id
      player_b -> room_id

11. Both players receive MATCH_FOUND.

12. A player sends a move through the WebSocket connection.

13. Gateway reads the player's room_id.

14. Gateway resolves room_id -> game_server_id.

15. Message is routed to the authoritative Game Server.

16. GameSession and GameEngine validate and process the move.

17. Resulting state/events are sent to both players.

18. Game ends after approximately 30–90 seconds.

19. Game Server sends final result to Rating Service.

20. Rating Service updates PostgreSQL transactionally.

21. Room mappings are removed from Redis.

22. GameSession is deleted and its memory is released.

23. The Game Server remains alive and can host new games.
```

---

# 21. Proposed Architecture Diagram

```text
                                 +----------------------+
                                 |      PostgreSQL      |
                                 | users / ratings /    |
                                 | persistent history   |
                                 +----------+-----------+
                                            ^
                                            |
                            +---------------+---------------+
                            |                               |
                     +------+-+                         +---+--------+
                     |  Auth  |                         |  Rating    |
                     | Service|                         |  Service   |
                     +--------+                         +------------+

Clients around the world
          |
          v
+---------------------------+
| Global Load Balancer      |
+-------------+-------------+
              |
              v
+---------------------------+
| WebSocket Gateway Pods    |
| connection + routing      |
+-------------+-------------+
              |
       +------+--------------------------+
       |                                 |
       v                                 v
+--------------+                  +-------------------+
| Matchmaking  |                  | Redis / Shared    |
| Service      |<---------------->| Fast State        |
+------+-------+                  |                   |
       |                          | player -> room    |
       |                          | room -> server    |
       |                          | queues / presence |
       |                          +---------+---------+
       |                                    |
       v                                    |
+----------------------------------------------------------+
|                  Game Server Pool                        |
|                                                          |
|  +---------------+ +---------------+ +---------------+  |
|  | Game Server 1 | | Game Server 2 | | Game Server N |  |
|  | rooms 1..x    | | rooms ...     | | rooms ...     |  |
|  | GameSessions  | | GameSessions  | | GameSessions  |  |
|  | GameEngines   | | GameEngines   | | GameEngines   |  |
|  +---------------+ +---------------+ +---------------+  |
+----------------------------------------------------------+
```

---

# 22. מיפוי מהמימוש הנוכחי למימוש המוצע

| Current component     | Current state                             | Scaled design                                          |
| --------------------- | ----------------------------------------- | ------------------------------------------------------ |
| `GameWebSocketServer` | WebSocket + background loops בתוך שרת אחד | מספר Gateway/Game Server Pods                          |
| `ClientSessionRouter` | מנתב בתוך process יחיד                    | routing בין distributed services                       |
| `RoomManager`         | Rooms בזיכרון מקומי                       | local room ownership + shared Room Directory           |
| `GameSessionManager`  | כל sessions בזיכרון של שרת אחד            | כל Game Server מנהל רק את sessions שהוקצו אליו         |
| `MatchmakingService`  | queue מקומי                               | distributed/shared matchmaking queue                   |
| `ReconnectManager`    | reconnect state מקומי                     | reconnect metadata משותף                               |
| `UserRepository`      | SQLite file                               | PostgreSQL                                             |
| `RatingService`       | עדכון מול אותו SQLite                     | service שמעדכן persistent DB                           |
| `GameSession`         | authoritative game state                  | נשאר authoritative, אבל רק ל־Rooms של אותו Game Server |
| `GameEngine`          | game logic                                | נשאר כמעט ללא תלות בארכיטקטורת הענן                    |

אחד היתרונות במבנה הקיים הוא שה־`GameEngine` מופרד יחסית משכבת ה־WebSocket. לכן אין צורך לכתוב מחדש את חוקי המשחק כדי לבצע Scale. עיקר השינוי הוא בשכבת ה־server infrastructure, persistence ו־routing.

---

# 23. החלטות מרכזיות

ה־Design המוצע מבוסס על ההחלטות הבאות:

1. **SQLite לא מתאים ל־production scale** של 100 מיליון משתמשים ומספר רב של server instances.
2. **PostgreSQL** ישמש לנתונים קבועים כגון משתמשים ו־ratings.
3. **Redis** ישמש לנתונים זמניים ומשותפים במהירות גבוהה.
4. המערכת תרוץ על **מספר רב של Docker containers**.
5. Kubernetes/K3s ישמש לניהול ה־containers ול־horizontal scaling.
6. חיבורי WebSocket יתקבלו דרך שכבת Gateway.
7. matchmaking יהיה משותף לכל השרתים ולא queue מקומי.
8. לכל Room יהיה **Game Server authoritative אחד** בזמן נתון.
9. יישמר mapping משותף של:
   `room_id -> game_server_id`.
10. כל Game Server יחזיק מספר רב של Game Sessions.
11. GameSession הוא קצר־חיים, אך Game Server container הוא ארוך־חיים.
12. בסיום משחק יישמר רק המידע שצריך לשרוד, וה־GameSession יימחק.
13. scaling יבוצע על בסיס metrics אמיתיים ולא באמצעות מספר שרתים שנבחר מראש.
14. בפריסה גלובלית יועדף Game Server קרוב גיאוגרפית לשחקנים כדי להקטין latency.

---

# 24. סיכום

השרת הנוכחי של Kung-Fu Chess הוא בסיס טוב לשרת multiplayer, אך הוא מניח process יחיד שבו כל המידע נמצא באותו זיכרון.

כדי לתמוך ב־100 מיליון משתמשים רשומים וב־10 מיליון שחקנים פעילים בו־זמנית צריך לעבור למערכת מבוזרת.

האתגר המרכזי אינו רק "להריץ עוד Dockerים". ברגע שמריצים כמה instances, צריך לפתור את שאלת ה־state:

* איפה נשמר משתמש?
* איפה נמצא Room?
* איזה Game Server מחזיק את המשחק?
* איך שחקנים שמחוברים לשרתים שונים נפגשים?
* איך הודעה מגיעה תמיד לשרת שמחזיק את ה־GameSession הנכון?

הפתרון המוצע מפריד בין data קבוע, data זמני ו־live game state:

```text
PostgreSQL -> persistent users and ratings
Redis      -> shared routing and temporary state
GameServer -> authoritative live GameSession
```

מעליהם נמצאים Gateway, Matchmaking ושירותים נוספים שניתן להגדיל אופקית.

ב־10 מיליון שחקנים פעילים מתקבלים בערך:

```text
5 million concurrent games
5 million moves per second
~500 MB/sec raw inbound move payload
~4 Gbit/sec raw inbound move traffic
```

לפני response traffic ו־network protocol overhead.

לכן שרת יחיד אינו פתרון אפשרי, אך מערכת שמחלקת את העומס בין מספר גדול של Game Servers, regions ו־network links יכולה לגדול בהתאם לצורך.

העיקרון החשוב ביותר הוא שה־Game Engine עצמו יכול להישאר כמעט כפי שהוא, בעוד ששכבת השרת מסביבו משתנה משרת יחיד ל־distributed cloud architecture.
