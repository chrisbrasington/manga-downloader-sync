# Learning Lua & the KOReader plugin — a guide for C# developers

A three-lesson walkthrough of Lua and how the `mangalibrary.koplugin` is built and
works, written for someone coming from C#. Lesson 1 is the language, Lesson 2 is the
KOReader framework, Lesson 3 traces one real user action through `main.lua`.

---

# Lesson 1 — Lua for a C# developer

## The three things that'll trip you up first

1. **There's basically one data structure: the `table`.** A Lua table is your
   `List<T>`, your `Dictionary<TKey,TValue>`, and your `class`/object, all at once.
2. **Arrays start at index `1`, not `0`.** `t[1]` is the first element; `#t` is the count.
3. **Truthiness is narrow.** Only `false` and `nil` are falsy. `0`, `""`, and empty
   tables are all **truthy**.

## Syntax cheat sheet

| Concept | C# | Lua |
|---|---|---|
| Local variable | `var x = 5;` | `local x = 5` |
| Null | `null` | `nil` |
| Null-coalesce | `x ?? def` | `x or def` |
| Ternary | `c ? a : b` | `c and a or b` |
| String concat | `a + b` | `a .. b` |
| Not / and / or | `! && \|\|` | `not and or` |
| Not-equal | `!=` | `~=` |
| Count | `list.Count` | `#list` |
| Comment | `// ...` | `-- ...` |
| Block comment | `/* */` | `--[[ ]]` |
| Statement terminator | `;` | none (newlines) |

Lua is **dynamically typed** (no type annotations). `local` matters: without it a
variable is global. Rule of thumb: always write `local`.

## Tables — the one structure

```lua
-- As an array (List<T>):
local fruits = { "apple", "banana", "cherry" }
print(fruits[1])      -- "apple"  (1-based!)
print(#fruits)        -- 3

-- As a dictionary (Dictionary<string, object>):
local person = { name = "Sam", age = 30 }
print(person.name)    -- "Sam"      (dot access)
print(person["age"])  -- 30         (same thing, string-key access)
```

`person.name` and `person["name"]` are identical — dot is sugar for a string key.

**`nil` removes keys.** Setting a key to `nil` deletes it; reading a missing key
returns `nil`. This caused a real bug: the JSON library returned a special non-`nil`
value for JSON `null`, so `m.last_read_page or 1` didn't fall back to `1`. The fix:

```lua
local function denull(v)
    if type(v) == "table" then           -- type() ~ GetType().Name as a string
        for k, val in pairs(v) do         -- foreach over EVERY key (dictionary-style)
            if val == JSON_NULL then
                v[k] = nil                -- delete this key
            elseif type(val) == "table" then
                denull(val)               -- recurse into nested tables
            end
        end
    end
    return v
end
```

- `pairs(t)` — iterate all key/value pairs (like `foreach` over a `Dictionary`).
- `ipairs(t)` — iterate the array part `1,2,3…` until the first `nil` (like a `List`).
- `type(x)` — returns a string: `"table"`, `"string"`, `"number"`, `"nil"`, `"function"`, `"boolean"`.

## Functions are values (delegates/lambdas)

```lua
local function add(a, b) return a + b end
local add = function(a, b) return a + b end   -- identical
```

Functions capture surrounding locals (closures), like C# lambdas. The plugin stores
`callback = function() ... end` on menu items, capturing `self`, `api`, etc.

## `:` vs `.` — Lua's "OOP"

Lua has **no classes**. A method is a function stored in a table. The colon is the
only special piece:

```lua
function MangaLibrary:getBaseUrl()
    return self.settings:readSetting("base_url") or DEFAULT_BASE_URL
end
```

- Defining with `:` adds a hidden first parameter `self` (C#'s implicit `this`).
- Calling with `:` passes the receiver as `self`.

So `obj:method(x)` == `obj.method(obj, x)`. As C#:

```csharp
string GetBaseUrl() => this.settings.ReadSetting("base_url") ?? DEFAULT_BASE_URL;
```

## A real example end to end

```lua
local FILTERS = {
    { key = "all",       text = _("All") },
    { key = "favorites", text = _("Favorites") },
    { key = "reading",   text = _("Reading") },
}
```

A table-as-`List` whose elements are tables-as-records. Matching one:

```lua
local function matchesFilter(m, key)
    if key == "all" then return not m.hidden end
    if key == "reading" then return m.last_read_chapter ~= nil and not m.hidden end
end
```

Iterating with a count:

```lua
local count = 0
for _i, m in ipairs(self._library) do      -- foreach (manga m in this.library)
    if matchesFilter(m, key) then count = count + 1 end
end
```

`_i` (leading underscore) = "unused," like C#'s `_`. No `++`/`+=` in Lua.

**Core takeaway:** tables for everything, `nil`/truthiness, `or` for defaults, `..`
for strings, `:`/`self` for methods, closures for callbacks.

---

# Lesson 2 — how the KOReader plugin is wired up

Big shift from C#: there's **no explicit wiring**. You name methods a certain way
and the framework finds and calls them.

## A. `require` — modules

```lua
local UIManager = require("ui/uimanager")
```

`require("x")` loads `x.lua`, runs it once (cached), and returns whatever it
`return`s. It's `using` + assembly reference + "get the exported thing." Each module
ends with `return SomeTable`. Your plugin ends with `return MangaLibrary`.

## B. "Classes" are tables wired with metatables

A **metatable** customizes how a table behaves. The key metamethod is `__index`:

> Look up a missing key on a table, and Lua checks the metatable's `__index` instead.

That gives method lookup and inheritance. `MangaApi` is a hand-rolled class:

```lua
local MangaApi = {}
MangaApi.__index = MangaApi              -- missing keys fall through to MangaApi itself

function MangaApi.new(base_url)          -- factory (dot, no self)
    local url = base_url or DEFAULT_BASE_URL
    return setmetatable({ base_url = url }, MangaApi)   -- instance; "vtable" = MangaApi
end

function MangaApi:getJson(path) return self:_request("GET", path) end   -- instance method
```

`MangaApi` is the class/vtable; an instance is `{ base_url=... }` whose metatable is
`MangaApi`. `api:getJson(...)` isn't on the instance, so `__index` finds it on the class.

## C. The framework's class helper: `:extend` and `:new`

KOReader's base `Widget` provides `extend` (subclass) and `new` (instantiate):

```lua
local MangaReader = InputContainer:extend{ chapter_index = 1, page = 1, prefetch_ahead = 1 }
local MangaLibrary = WidgetContainer:extend{ name = "mangalibrary" }
```

- `Base:extend{ ... }` makes a subclass; the `{ ... }` are **default field values**.
- Inheritance is the `__index` chain: instance → MangaReader → InputContainer → … → Widget.
- `Class:new{ ... }` builds an instance, copies the fields over the defaults, sets the
  metatable, then calls `self:init()`. **`init` is your constructor.**

## D. How KOReader finds and starts the plugin

```
mangalibrary.koplugin/
  _meta.lua     -- metadata: returns { name=, fullname=, description= }
  main.lua      -- returns the plugin class
```

1. KOReader scans `plugins/*.koplugin/` at startup.
2. Reads `_meta.lua` for the menu listing.
3. Loads `main.lua`, gets `MangaLibrary`, does `MangaLibrary:new{ ui = <host> }` → `init`:

```lua
function MangaLibrary:init()
    self.settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/mangalibrary.lua")
    self.ui.menu:registerToMainMenu(self)   -- "call my addToMainMenu later"
end
```

`LuaSettings` is a key/value store backed by a `.lua` file — get/set/save via
`readSetting`/`saveSetting`/`flush`. It holds the server URL and prefetch count.

## E. The event model (no C# equivalent)

KOReader runs a single-threaded **event loop**. Input becomes a named **Event**,
dispatched to on-screen widgets. A widget handles event `Foo` by having a method
`onFoo` — no subscription, name-based dispatch. Returning `true` **consumes** the
event (like `e.Handled = true`).

For gestures, declare regions → event names in `init`:

```lua
self.ges_events = {
    TapPrev = { GestureRange:new{ ges = "tap", range = Geom:new{ x = 0, y = 0, w = third, h = h } } },
    TapNext = { GestureRange:new{ ges = "tap", range = Geom:new{ x = w - third, y = 0, w = third, h = h } } },
    SwipeNav = { GestureRange:new{ ges = "swipe", range = Geom:new{ x = 0, y = 0, w = w, h = h } } },
}
```

Then write the matching methods:

```lua
function MangaReader:onTapNext() self:nextPage(); return true end
function MangaReader:onSwipeNav(_arg, ges)
    if ges.direction == "west" then self:nextPage()
    elseif ges.direction == "east" then self:prevPage() end
    return true
end
```

`return true` is why the reader is modal — it swallows gestures so widgets underneath
never react. `key_events` maps physical buttons the same way (`onKeyNext`, `onClose`).

## F. UIManager — window manager + paint loop

- `UIManager:show(widget)` — push a widget on top (modal overlay).
- `UIManager:close(widget)` — pop it; what was underneath reappears.
- `UIManager:setDirty(widget, "ui" | "full")` — mark for repaint. On e-ink, `"ui"` is
  a fast partial refresh, `"full"` is the slower flash that clears ghosting.
- `UIManager:scheduleIn(seconds, fn)` — run `fn` later on the UI thread.

**Single-threaded and cooperative** — no background threads. A blocking HTTP call
freezes the screen; prefetch is deferred with `scheduleIn` so the current page paints first.

## G. Widgets compose into a tree

By convention `self[1]` is a widget's child; layout containers arrange theirs:

```lua
self[1] = FrameContainer:new{                 -- background/border box
    background = Blitbuffer.COLOR_WHITE,
    VerticalGroup:new{                         -- stack top-to-bottom
        CenterContainer:new{ dimen = Geom:new{ w = w, h = h - bar_h }, self.image_widget },
        self:_buildProgressBar(),
    },
}
```

Like nesting elements in XAML/HTML. Swapping `self[1]` + `setDirty` redraws each page.
Every container needs its child — a childless `FrameContainer` crashes in `getSize`.

---

# Lesson 3 — a guided read of `main.lua`

Follow one journey: **tap "Manga Library" → Open library → tap a tag → pick a manga →
open a chapter → turn a page → close.**

## Step 0 — startup (constructor + menu registration)

`init` opens settings and registers the menu; KOReader then calls `addToMainMenu`,
where the menu is described **as data** (items with `callback` closures). `text_func`
recomputes a label each time the menu opens (e.g. "Server: …").

## Step 1 — Open library → `openLibrary`

```lua
function MangaLibrary:openLibrary()
    if not self:_haveServer() then return end          -- prompt if no URL set
    self:_online(function()                             -- ensure WiFi, then run
        local api = MangaApi.new(self:getBaseUrl())
        local list, err = api:getJson("/api/manga")     -- blocking HTTP + decode + denull
        if not list then UIManager:show(InfoMessage:new{ text = ... }); return end
        self._library = list                            -- session snapshot
        self:showFilterMenu(api)
    end)
end
```

`getJson` blocks (single thread), so no spinner can animate during it.

## Step 2 — the filter menu → `showFilterMenu`

```lua
function MangaLibrary:showFilterMenu(api)
    local menu                                          -- declared first so callbacks can capture it
    local function build()
        local items = { { text = _("Reload from server"), callback = function() ... end } }
        for _i, f in ipairs(FILTERS) do
            local key, count = f.key, 0
            for _j, m in ipairs(self._library) do
                if matchesFilter(m, key) then count = count + 1 end
            end
            table.insert(items, {
                text = f.text, mandatory = tostring(count),   -- mandatory = right-aligned
                callback = function() self:showList(api, f.text, function(m) return matchesFilter(m, key) end) end,
            })
        end
        table.insert(items, { text = _("Browse by tag"), callback = function() self:showTagMenu(api) end })
        return items
    end
    menu = self:_showMenu(_("Manga Library"), build())
end
```

Each filter passes a **predicate function** to `showList`. `_showMenu` creates the
`Menu` widget, shows it, and returns it:

```lua
function MangaLibrary:_showMenu(title, items)
    local menu = Menu:new{
        title = title, item_table = items,
        width = Screen:getWidth(), height = Screen:getHeight(),
        onMenuSelect = function(_self, item) if item.callback then item.callback() end end,
    }
    UIManager:show(menu)
    return menu
end
```

Each `_showMenu` stacks a new screen; Back pops it.

## Step 3 — tap a tag → `showTagMenu` → `showList`

```lua
self:showList(api, tag, function(m)
    if m.hidden then return false end
    for _j, mt in ipairs(m.tags or {}) do      -- "m.tags or {}" = ?? new[]{} (nil guard)
        if mt == tag then return true end
    end
    return false
end)
```

`showList` filters `self._library` with the predicate, builds a title menu, and each
title's callback calls `openManga`.

## Step 4 — pick a manga → `openManga`

```lua
function MangaLibrary:openManga(api, m)
    local detail = api:getJson("/api/manga/" .. urlencode(m.id))   -- includes chapters
    local chapters = detail.chapters
    local title = detail.alias or detail.english_title or detail.title  -- first non-nil
    local menu
    local function build_items()
        local items = {}
        if detail.last_read_chapter then ... end          -- "Continue" row when there's progress
        for idx = #chapters, 1, -1 do                      -- count DOWN: newest first
            local fn = chapters[idx]
            local resume_page = (fn == detail.last_read_chapter) and (detail.last_read_page or 1) or 1
            items[#items+1] = {
                text = fn:gsub("%.cbz$", ""),              -- gsub = regex replace
                callback = function()
                    if resume_page > 1 then self:_chooseStart(api, detail, chapters, idx, resume_page, menu)
                    else self:openReader(api, detail, chapters, idx, 1, menu) end
                end,
            }
        end
        return items
    end
    menu = self:_showMenu(title, build_items())
    menu._rebuild = function() menu:switchItemTable(title, build_items()) end   -- refresh after reading
end
```

## Step 5 — open a chapter → `openReader` → `MangaReader:new` → `init`

```lua
function MangaLibrary:openReader(api, manga, chapters, chapter_index, start_page, menu)
    local reader = MangaReader:new{                  -- :new runs init
        api = api, manga = manga, chapters = chapters,
        chapter_index = chapter_index, page = start_page or 1,
        prefetch_ahead = self:getPrefetch(),
        on_close = function(last_chapter, last_page)  -- fired on close
            manga.last_read_chapter = last_chapter
            manga.last_read_page = last_page
            self:_syncLibrary(manga.id, last_chapter, last_page)
            if menu and menu._rebuild then menu._rebuild() end
        end,
    }
    UIManager:show(reader)
end
```

`init` sets gesture zones, puts a paintable placeholder, then loads the chapter:

```lua
self[1] = self:_messageFrame(_("Loading…"))
self:loadChapter(self.chapter_index, self.page)
```

## Step 6 — load + show the first page → `loadChapter` → `setPage`

```lua
function MangaReader:loadChapter(idx, start_page)
    self.chapter_index = idx
    self.page_data = {}                              -- per-chapter in-memory page cache
    local info = self.api:getJson(T("/cbz/%1/%2/info", urlencode(self.manga.id), urlencode(fn)))
    self.total_pages = (info and info.page_count) or 0
    if self.total_pages == 0 then ... return end
    self:setPage(math.min(math.max(start_page or 1, 1), self.total_pages))   -- clamp
end

function MangaReader:setPage(n)
    if not (self.page_data and self.page_data[n]) then
        self[1] = self:_messageFrame(T(_("Loading page %1…"), n)); UIManager:setDirty(self, "ui"); UIManager:forceRePaint()
    end
    local data, err = self:_fetchPage(n)             -- cache or HTTP (getBytes)
    if not data then ... return end
    local bb = RenderImage:renderImageData(data, #data)   -- JPEG bytes -> bitmap
    self.page = n
    if self.image_widget then self.image_widget:free() end
    self.image_widget = ImageWidget:new{ image = bb, image_disposable = true, scale_factor = 0, ... }
    self[1] = FrameContainer:new{ VerticalGroup:new{ CenterContainer:new{ ..., self.image_widget }, self:_buildProgressBar() } }
    UIManager:setDirty(self, "full")
    self:_scheduleProgress()                         -- debounced save to server
    self:_evict(n - 1, n + self.prefetch_ahead + 1)  -- drop far-away cached pages
    if self.prefetch_ahead > 0 then
        UIManager:scheduleIn(0.15, function() for i = 1, self.prefetch_ahead do self:_fetchPage(n + i) end end)
    end
end
```

Ties it together: fetch bytes → `RenderImage` bitmap → widget tree in `self[1]` →
`setDirty` → prefetch after paint (cooperative threading).

## Step 7 — turn a page → gesture → `onTapNext` → `nextPage`

```lua
function MangaReader:onTapNext() self:nextPage(); return true end

function MangaReader:nextPage()
    if self.page < self.total_pages then self:setPage(self.page + 1)
    elseif self.chapter_index < #self.chapters then self:loadChapter(self.chapter_index + 1, 1)
    else self:onClose(); UIManager:show(InfoMessage:new{ text = _("End of manga."), timeout = 2 }) end
end
```

A prefetched page is already in `page_data`, so `setPage` skips HTTP. `onTapMenu`
shows a `ButtonDialog` titled `Page X / Y`; pinch/spread (`onZoomSpread`/`onZoomPinch`)
call `_openZoom`, rendering a fresh bitmap for KOReader's `ImageViewer` (pan/zoom).

## Step 8 — close → `onClose`

```lua
function MangaReader:onClose()
    if self._progress_scheduled then UIManager:unschedule(self._flush_progress_fn); self:_flushProgress() end
    if self.image_widget then self.image_widget:free() end   -- release bitmap
    self.page_data = nil                                     -- let GC reclaim pages
    UIManager:close(self)                                    -- pop reader
    if self.on_close then self.on_close(self.chapters[self.chapter_index], self.page) end
    UIManager:setDirty("all", "ui")                          -- repaint revealed menu
    return true
end
```

`_flushProgress` does `PATCH /api/manga/{id}` (save to server); `on_close` updates the
caches and rebuilds the chapter menu so the new resume point shows.

---

## The rhythm of the whole file

- Every screen = `_showMenu` / `UIManager:show` pushing a widget onto the stack.
- Every action = a gesture firing an `onX` method (return `true` to consume it).
- Data flows: `MangaApi:getJson`/`getBytes` → tables/bitmaps → a widget tree in
  `self[1]` → `setDirty` to repaint.
- One cooperative thread: blocking calls freeze the UI; defer with `scheduleIn`.

Once you see that rhythm, the rest of the file is variations on it.

## Where things live in `main.lua`

| Area | Functions |
|---|---|
| HTTP client | `MangaApi.new`, `MangaApi:_request`, `:getJson`, `:getBytes`, `:patch` |
| JSON null fix | `denull` |
| Plugin entry / menu | `MangaLibrary:init`, `:addToMainMenu`, `:editServer`, `:_prefetchOption` |
| Server config | `:getBaseUrl`, `:getPrefetch`, `:_haveServer`, `:testConnection`, `:_hint` |
| Browsing | `:openLibrary`, `:showFilterMenu`, `:showTagMenu`, `:showList`, `matchesFilter`, `FILTERS` |
| Chapter list | `:openManga`, `:_chooseStart`, `:_showMenu`, `:_syncLibrary` |
| Reader | `MangaReader:init`, `:loadChapter`, `:setPage`, `:_fetchPage`, `:_evict` |
| Reader UI | `:_messageFrame`, `:_buildProgressBar`, `:bar_height` |
| Reader input | `:onTapNext/Prev/Menu`, `:onSwipeNav`, `:onZoomSpread/Pinch`, `:_openZoom`, `:_goToPage` |
| Navigation | `:nextPage`, `:prevPage` |
| Progress sync | `:_scheduleProgress`, `:_flushProgress`, `:onClose` |
