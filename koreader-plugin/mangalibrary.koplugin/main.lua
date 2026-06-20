--[[
Manga Library — KOReader plugin

Browses and reads manga served by the manga-api container. All content
is fetched over WiFi; pages arrive as pre-rendered grayscale JPEGs sized for the
device. Reading progress is written back to the shared manga.db so the browser
webapp and the Kobo stay in sync.

The server address is set on the device (Manga Library → Server); there is no
hardcoded default. Point it at the backend's LAN address, e.g. http://<host>:8684.
]]

local Device = require("device")
local Screen = Device.screen
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local InputContainer = require("ui/widget/container/inputcontainer")
local FrameContainer = require("ui/widget/container/framecontainer")
local CenterContainer = require("ui/widget/container/centercontainer")
local RightContainer = require("ui/widget/container/rightcontainer")
local OverlapGroup = require("ui/widget/overlapgroup")
local VerticalGroup = require("ui/widget/verticalgroup")
local HorizontalGroup = require("ui/widget/horizontalgroup")
local ImageWidget = require("ui/widget/imagewidget")
local ImageViewer = require("ui/widget/imageviewer")
local RenderImage = require("ui/renderimage")
local ProgressWidget = require("ui/widget/progresswidget")
local TextWidget = require("ui/widget/textwidget")
local TextBoxWidget = require("ui/widget/textboxwidget")
local Menu = require("ui/widget/menu")
local InfoMessage = require("ui/widget/infomessage")
local Notification = require("ui/widget/notification")
local InputDialog = require("ui/widget/inputdialog")
local ButtonDialog = require("ui/widget/buttondialog")
local GestureRange = require("ui/gesturerange")
local Geom = require("ui/geometry")
local Font = require("ui/font")
local Blitbuffer = require("ffi/blitbuffer")
local NetworkMgr = require("ui/network/manager")
local DataStorage = require("datastorage")
local LuaSettings = require("luasettings")
local _ = require("gettext")
local T = require("ffi/util").template

-- networking
local http = require("socket.http")
local https = require("ssl.https")
local ltn12 = require("ltn12")
local socket = require("socket")
local socketutil = require("socketutil")
local socket_url = require("socket.url")
local rapidjson = require("rapidjson")

-- No hardcoded server: the user sets the address on the device (Manga Library →
-- Server). Until then getBaseUrl() returns "" and actions prompt for it.
local DEFAULT_BASE_URL = ""

-- rapidjson decodes JSON null to a sentinel (rapidjson.null), not Lua nil, which
-- is truthy and breaks `x or default` and `x ~= nil` checks. Convert it to real nil.
local JSON_NULL = rapidjson.null
local function denull(v)
    if type(v) == "table" then
        for k, val in pairs(v) do
            if val == JSON_NULL then
                v[k] = nil
            elseif type(val) == "table" then
                denull(val)
            end
        end
    end
    return v
end

-- The nine webapp library filters, plus tag browsing, mirrored here.
-- Plain-text labels only: KOReader's bundled fonts don't render emoji glyphs.
local FILTERS = {
    { key = "all",         text = _("All") },
    { key = "favorites",   text = _("Favorites") },
    { key = "reading",     text = _("Reading") },
    { key = "lastread",    text = _("Last Read"), recent = true },
    { key = "downloading", text = _("Downloading") },
    { key = "completed",   text = _("Completed") },
    { key = "hiatus",      text = _("Hiatus") },
    { key = "archived",    text = _("Archived") },
    { key = "read",        text = _("Read") },
    { key = "hidden",      text = _("Hidden") },
}

local function matchesFilter(m, key)
    if key == "all" then return not m.hidden end
    if key == "favorites" then return m.favorited and not m.hidden end
    if key == "reading" then return m.last_read_chapter ~= nil and not m.hidden end
    if key == "lastread" then return m.last_read_at ~= nil and not m.hidden end
    if key == "downloading" then return m.download_enabled and not m.hidden end
    if key == "completed" then return m.status == "completed" and not m.hidden end
    if key == "hiatus" then return m.status == "hiatus" and not m.hidden end
    if key == "archived" then return m.status == "archived" and not m.hidden end
    if key == "read" then return m.read and not m.hidden end
    if key == "hidden" then return m.hidden end
    return true
end

-- Sort most-recently-read first. Timestamps are UTC strings (YYYY-MM-DD HH:MM:SS),
-- so a plain string comparison orders them correctly.
local function byRecent(a, b) return (a.last_read_at or "") > (b.last_read_at or "") end

-------------------------------------------------------------------------------
-- API client
-------------------------------------------------------------------------------

local MangaApi = {}
MangaApi.__index = MangaApi

function MangaApi.new(base_url)
    local url = base_url or DEFAULT_BASE_URL
    -- Keep only scheme://host:port — drop any path/query the user may have pasted
    -- (e.g. ".../api/manga"), which would otherwise be doubled onto every request.
    local root = url:match("^%s*(%a[%w+.%-]*://[^/]+)")
    return setmetatable({ base_url = root or (url:gsub("/+$", "")) }, MangaApi)
end

-- mode: "json" (decode body) | "raw" (return body string). Everything is fetched
-- into memory via a table sink — the same path the working JSON calls use — so there
-- is no dependency on writable temp files on the device.
function MangaApi:_request(method, path, body_tbl, mode)
    mode = mode or "json"
    local url = self.base_url .. path
    local requester = url:sub(1, 6) == "https:" and https.request or http.request
    local headers = {}
    local source, body
    if body_tbl then
        body = rapidjson.encode(body_tbl)
        source = ltn12.source.string(body)
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = tostring(#body)
    end
    local result_tbl = {}
    local req = {
        url = url, method = method, headers = headers, source = source,
        sink = ltn12.sink.table(result_tbl),
    }
    if requester == https.request then
        -- Be permissive so a self-hosted cert / modern TLS negotiates cleanly.
        req.protocol = "any"
        req.options = "all"
        req.verify = "none"
    end

    socketutil:set_timeout(10, 60)
    -- table form returns (1, code, headers, status) on success, (nil, err) on failure
    local ok, code = requester(req)
    socketutil:reset_timeout()

    if ok == nil then
        -- socket-level failure: DNS, connection refused, TLS handshake, timeout…
        return nil, tostring(code)
    end
    if code ~= 200 then
        return nil, "HTTP " .. tostring(code)
    end

    local data = table.concat(result_tbl)
    if mode == "raw" then
        if #data == 0 then return nil, "empty response" end
        return data
    end
    local decoded = rapidjson.decode(data)
    if decoded == nil then return nil, "invalid JSON from server" end
    return denull(decoded)
end

function MangaApi:getJson(path) return self:_request("GET", path) end

function MangaApi:patch(path, tbl) return self:_request("PATCH", path, tbl) end

-- Returns raw image bytes (string) or nil, err.
function MangaApi:getBytes(path) return self:_request("GET", path, nil, "raw") end

local function urlencode(s) return socket_url.escape(s or "") end

-- Parse the /api/covers binary stream into { [id] = jpeg_bytes }.
-- Format: [u8 count] then per item [u8 id_len][id bytes][u32 big-endian img_len][jpeg].
-- Every read is bounds-checked: a truncated stream (Wi-Fi dropped mid-transfer)
-- yields a partial table rather than crashing the parser.
local function parse_cover_stream(data)
    local out = {}
    local n = #data
    if n < 1 then return out end
    local count = data:byte(1)
    local cur = 2
    for _ = 1, count do
        if cur > n then break end
        local id_len = data:byte(cur); cur = cur + 1
        if cur + id_len - 1 > n then break end
        local id = data:sub(cur, cur + id_len - 1); cur = cur + id_len
        if cur + 3 > n then break end
        local b1, b2, b3, b4 = data:byte(cur, cur + 3); cur = cur + 4
        local img_len = b1 * 16777216 + b2 * 65536 + b3 * 256 + b4
        if img_len <= 0 or cur + img_len - 1 > n then break end
        out[id] = data:sub(cur, cur + img_len - 1); cur = cur + img_len
    end
    return out
end

-- Fetch many small grayscale covers in one request (the grid loads a whole page
-- with one blocking call instead of N). ids: array of manga ids; w: card width.
-- Returns { [id] = jpeg_bytes } (ids the server can't produce a cover for are
-- simply absent), or nil, err on a transport failure.
function MangaApi:getCovers(ids, w)
    local joined = urlencode(table.concat(ids, ","))
    local data, err = self:getBytes(T("/api/covers?w=%1&ids=%2", w, joined))
    if not data then return nil, err end
    return parse_cover_stream(data)
end

-------------------------------------------------------------------------------
-- Reader widget: one page image at a time, tap zones, prefetch, chapter flow
-------------------------------------------------------------------------------

local MangaReader = InputContainer:extend{
    api = nil,
    manga = nil,        -- manga payload (id, title, last_read_*)
    chapters = nil,     -- sorted ascending list of chapter filenames
    chapter_index = 1,
    page = 1,
    total_pages = 0,
    prefetch_ahead = 1,
    crop = true,        -- ask the backend to trim uniform page margins
    page_width = nil,
    on_close = nil,     -- function(last_chapter, last_page) called when reader closes
    plugin = nil,       -- the MangaLibrary instance, for Main Menu / Close app
}

function MangaReader:init()
    self.page_width = Screen:getWidth()
    self.covers_fullscreen = true
    local w, h = Screen:getWidth(), Screen:getHeight()
    self.dimen = Geom:new{ x = 0, y = 0, w = w, h = h }
    local third = math.floor(w / 3)
    if Device:isTouchDevice() then
        -- Tap zones: left third = prev, right third = next, centre = menu (with Close).
        -- Swipes page too, and we consume every gesture so the reader stays modal
        -- (nothing leaks to the menu/file-browser underneath).
        self.ges_events = {
            TapPrev = { GestureRange:new{ ges = "tap",
                range = Geom:new{ x = 0, y = 0, w = third, h = h } } },
            TapNext = { GestureRange:new{ ges = "tap",
                range = Geom:new{ x = w - third, y = 0, w = third, h = h } } },
            TapMenu = { GestureRange:new{ ges = "tap",
                range = Geom:new{ x = third, y = 0, w = w - 2 * third, h = h } } },
            SwipeNav = { GestureRange:new{ ges = "swipe",
                range = Geom:new{ x = 0, y = 0, w = w, h = h } } },
            -- Pinch/spread opens a zoomable view of the current page.
            ZoomSpread = { GestureRange:new{ ges = "spread",
                range = Geom:new{ x = 0, y = 0, w = w, h = h } } },
            ZoomPinch = { GestureRange:new{ ges = "pinch",
                range = Geom:new{ x = 0, y = 0, w = w, h = h } } },
        }
    end
    if Device:hasKeys() then
        self.key_events = {
            KeyNext = { { Device.input.group.PgFwd } },
            KeyPrev = { { Device.input.group.PgBack } },
            Close = { { "Back" } },
        }
    end
    -- Always have a paintable, full-screen child so the reader can never become an
    -- unclosable blank window even if the first page fails to load. A FrameContainer
    -- MUST wrap a child widget, so we use a centred message rather than an empty frame.
    self[1] = self:_messageFrame(_("Loading…"))
    self:loadChapter(self.chapter_index, self.page)
end

-- A full-screen frame showing centred text. Used as the initial placeholder and for
-- error states, so self[1] is always a paintable FrameContainer with a child.
function MangaReader:_messageFrame(text)
    local w, h = Screen:getWidth(), Screen:getHeight()
    return FrameContainer:new{
        background = Blitbuffer.COLOR_WHITE, bordersize = 0,
        CenterContainer:new{
            dimen = Geom:new{ w = w, h = h },
            TextWidget:new{ text = text, face = Font:getFace("infofont") },
        },
    }
end

function MangaReader:_pagePath(n)
    local fn = self.chapters[self.chapter_index]
    return T("/cbz/%1/%2/%3?w=%4&crop=%5",
        urlencode(self.manga.id), urlencode(fn), n, self.page_width, self.crop and 1 or 0)
end

-- Fetch page n's JPEG bytes (string), caching in memory. Returns data or nil, err.
function MangaReader:_fetchPage(n)
    if n < 1 or (self.total_pages > 0 and n > self.total_pages) then return nil, "out of range" end
    self.page_data = self.page_data or {}
    if self.page_data[n] then return self.page_data[n] end
    local data, err = self.api:getBytes(self:_pagePath(n))
    if not data then return nil, err end
    self.page_data[n] = data
    return data
end

-- Drop cached page bytes outside [keep_from, keep_to] to bound memory.
function MangaReader:_evict(keep_from, keep_to)
    if not self.page_data then return end
    for k in pairs(self.page_data) do
        if k < keep_from or k > keep_to then self.page_data[k] = nil end
    end
end

-- Kobo turns Wi-Fi off when it sleeps, so the first request after waking fails.
-- Show a status frame, bring the network back up, and run retry() once online.
function MangaReader:_reconnectThen(retry)
    self[1] = self:_messageFrame(NetworkMgr:isOnline()
        and _("Retrying…")
        or _("Connection lost — reconnecting Wi-Fi…"))
    UIManager:setDirty(self, "ui")
    UIManager:forceRePaint()
    NetworkMgr:runWhenOnline(function() retry() end)
end

function MangaReader:loadChapter(idx, start_page, attempt)
    if idx < 1 or idx > #self.chapters then return end
    attempt = attempt or 1
    self.chapter_index = idx
    self.page_data = {}   -- page cache is per-chapter
    local fn = self.chapters[idx]
    local info, ierr = self.api:getJson(T("/cbz/%1/%2/info", urlencode(self.manga.id), urlencode(fn)))
    if not info then
        -- request failed (likely Wi-Fi dropped on sleep): reconnect and retry once
        if attempt == 1 then
            self:_reconnectThen(function() self:loadChapter(idx, start_page, 2) end)
            return
        end
        self[1] = self:_messageFrame(T(_("Could not load chapter.\n%1"), ierr or "?"))
        UIManager:setDirty(self, "ui")
        return
    end
    self.total_pages = info.page_count or 0
    if self.total_pages == 0 then
        self[1] = self:_messageFrame(_("This chapter has no pages."))
        UIManager:setDirty(self, "ui")
        return
    end
    self:setPage(math.min(math.max(start_page or 1, 1), self.total_pages))
end

function MangaReader:setPage(n, attempt)
    attempt = attempt or 1
    -- show a Loading frame immediately if this page isn't cached yet
    if not (self.page_data and self.page_data[n]) then
        self[1] = self:_messageFrame(T(_("Loading page %1…"), n))
        UIManager:setDirty(self, "ui")
        UIManager:forceRePaint()
    end

    local data, err = self:_fetchPage(n)
    if not data then
        -- fetch failed (likely Wi-Fi dropped on sleep): reconnect and retry once
        if attempt == 1 then
            self:_reconnectThen(function() self:setPage(n, 2) end)
            return
        end
        self[1] = self:_messageFrame(T(_("Failed to load page %1.\n%2"), n, err or "?"))
        UIManager:setDirty(self, "full")
        return
    end

    -- Decode JPEG bytes straight from memory into a BlitBuffer (no temp file).
    local bb = RenderImage:renderImageData(data, #data)
    if not bb then
        self.page_data[n] = nil
        self[1] = self:_messageFrame(T(_("Could not decode page %1."), n))
        UIManager:setDirty(self, "full")
        return
    end

    self.page = n
    local w, h = Screen:getWidth(), Screen:getHeight()
    local bar_h = self:bar_height()
    if self.image_widget then self.image_widget:free() end
    self.image_widget = ImageWidget:new{
        image = bb,
        image_disposable = true,   -- ImageWidget owns and frees this BlitBuffer
        width = w,
        height = h - bar_h,
        scale_factor = 0,          -- scale to fit, keep aspect
        center = true,
    }
    self[1] = FrameContainer:new{
        background = Blitbuffer.COLOR_WHITE,
        bordersize = 0,
        VerticalGroup:new{
            CenterContainer:new{
                dimen = Geom:new{ w = w, h = h - bar_h },
                self.image_widget,
            },
            self:_buildProgressBar(),
        },
    }
    UIManager:setDirty(self, "full")
    self:_scheduleProgress()

    -- Let the plugin update the device sleep screen with the cover or this page.
    if self.plugin then self.plugin:onReaderPage(self.api, self.manga, data) end

    -- prefetch ahead into memory, after this page paints
    self:_evict(n - 1, n + self.prefetch_ahead + 1)
    if self.prefetch_ahead > 0 then
        UIManager:scheduleIn(0.15, function()
            for i = 1, self.prefetch_ahead do self:_fetchPage(n + i) end
        end)
    end
end

function MangaReader:bar_height() return Screen:scaleBySize(4) end

-- A very thin bottom progress bar: fraction filled = current page / total.
function MangaReader:_buildProgressBar()
    local pct = (self.total_pages > 0) and (self.page / self.total_pages) or 0
    return ProgressWidget:new{
        width = Screen:getWidth(),
        height = self:bar_height(),
        percentage = pct,
        margin_h = 0,
        margin_v = 0,
        radius = 0,
        bordersize = 0,
        bgcolor = Blitbuffer.COLOR_GRAY,
        fillcolor = Blitbuffer.COLOR_BLACK,
    }
end

function MangaReader:onTapNext() self:nextPage(); return true end
function MangaReader:onTapPrev() self:prevPage(); return true end
function MangaReader:onKeyNext() self:nextPage(); return true end
function MangaReader:onKeyPrev() self:prevPage(); return true end

-- All swipes are consumed (the reader is modal). Mapping:
--   left/right (west/east)         -> next/previous page
--   down from the top edge         -> the page menu (same as a centre tap)
--   up/down in the LEFT third      -> frontlight brightness
--   up/down in the RIGHT third     -> warmth (red/night light)
function MangaReader:onSwipeNav(_arg, ges)
    local dir = ges and ges.direction
    local pos = ges and ges.pos
    local x = (pos and pos.x) or 0
    local y = (pos and pos.y) or 0
    local w, h = Screen:getWidth(), Screen:getHeight()

    if dir == "west" then
        self:nextPage()
    elseif dir == "east" then
        self:prevPage()
    elseif dir == "north" or dir == "south" then
        local up = (dir == "north")                  -- "north" = finger moved upward
        if dir == "south" and y < h * 0.15 then
            self:onTapMenu()                          -- swipe down from the top edge -> menu
        elseif x < w / 3 then
            self:_adjustBrightness(up and 1 or -1)
        elseif x > w * 2 / 3 then
            self:_adjustWarmth(up and 1 or -1)
        end
    end
    return true
end

function MangaReader:_notify(text)
    UIManager:show(Notification:new{ text = text })
end

-- Step the frontlight up/down (delta = +1 / -1). No-op on devices without a frontlight.
function MangaReader:_adjustBrightness(delta)
    if not Device:hasFrontlight() then return end
    local p = Device.powerd
    local lo, hi = p.fl_min or 0, p.fl_max or 100
    local step = math.max(1, math.floor((hi - lo) / 10))
    local cur = p:frontlightIntensity() or lo
    local v = math.max(lo, math.min(hi, cur + delta * step))
    pcall(function() p:setIntensity(v) end)
    self:_notify(T(_("Brightness: %1"), v))
end

-- Step the warmth (red/night light) up/down. No-op without a natural-light frontlight.
function MangaReader:_adjustWarmth(delta)
    if not Device:hasNaturalLight() then return end
    local p = Device.powerd
    local hi = p.fl_warmth_max or 100
    local step = math.max(1, math.floor(hi / 10))
    local cur = (p.frontlightWarmth and p:frontlightWarmth()) or p.fl_warmth or 0
    local v = math.max(0, math.min(hi, cur + delta * step))
    pcall(function() p:setWarmth(v) end)
    self:_notify(T(_("Warmth: %1"), v))
end

-- Pinch or spread opens KOReader's ImageViewer on the current page, which provides
-- pinch-zoom and panning. Closing it returns to the reader.
function MangaReader:onZoomSpread() return self:_openZoom() end
function MangaReader:onZoomPinch() return self:_openZoom() end

function MangaReader:_openZoom()
    local data = self.page_data and self.page_data[self.page]
    if not data then return true end
    local bb = RenderImage:renderImageData(data, #data)
    if not bb then return true end
    UIManager:show(ImageViewer:new{
        image = bb,
        image_disposable = true,   -- ImageViewer frees this BlitBuffer on close
        fullscreen = true,
        with_title_bar = false,
    })
    return true
end

function MangaReader:nextPage()
    if self.page < self.total_pages then
        self:setPage(self.page + 1)
    elseif self.chapter_index < #self.chapters then
        self:loadChapter(self.chapter_index + 1, 1)
    else
        -- Past the last page of the last chapter: leave the reader and return to the list.
        self:onClose()
        UIManager:show(InfoMessage:new{ text = _("End of manga."), timeout = 2 })
    end
end

function MangaReader:prevPage()
    if self.page > 1 then
        self:setPage(self.page - 1)
    elseif self.chapter_index > 1 then
        self:loadChapter(self.chapter_index - 1, 999999) -- clamped to last page
    end
end

function MangaReader:onTapMenu()
    local dialog
    dialog = ButtonDialog:new{
        title = T(_("%1\nPage %2 / %3"),
            self.chapters[self.chapter_index]:gsub("%.cbz$", ""), self.page, self.total_pages),
        title_align = "center",
        buttons = {
            -- Actions that hit the server (chapter load, Main Menu) ensure Wi-Fi
            -- is up first — runWhenOnline connects when offline, runs immediately
            -- when already online. "Close app" deliberately skips this.
            {{ text = _("Previous chapter"), enabled = self.chapter_index > 1, callback = function()
                UIManager:close(dialog)
                NetworkMgr:runWhenOnline(function() self:loadChapter(self.chapter_index - 1, 1) end) end }},
            {{ text = _("Next chapter"), enabled = self.chapter_index < #self.chapters, callback = function()
                UIManager:close(dialog)
                NetworkMgr:runWhenOnline(function() self:loadChapter(self.chapter_index + 1, 1) end) end }},
            {{ text = _("Go to page…"), callback = function()
                UIManager:close(dialog); self:_goToPage() end }},
            {{ text = _("Close Chapter"), callback = function()
                UIManager:close(dialog); self:onClose() end }},
            {{ text = _("Main Menu"), callback = function()
                UIManager:close(dialog); self:onClose()
                if self.plugin then
                    NetworkMgr:runWhenOnline(function() self.plugin:_goMainMenu(self.api) end)
                end end }},
            {{ text = _("Close app"), callback = function()
                UIManager:close(dialog); self:onClose()
                if self.plugin then self.plugin:_closeAll() end end }},
        },
    }
    UIManager:show(dialog)
    return true
end

function MangaReader:_goToPage()
    local input
    input = InputDialog:new{
        title = T(_("Go to page (1–%1)"), self.total_pages),
        input_type = "number",
        buttons = {{
            { text = _("Cancel"), callback = function() UIManager:close(input) end },
            { text = _("Go"), is_enter_default = true, callback = function()
                local n = tonumber(input:getInputText())
                UIManager:close(input)
                if n then self:setPage(math.min(math.max(n, 1), self.total_pages)) end
            end },
        }},
    }
    UIManager:show(input)
    input:onShowKeyboard()
end

-- Coalesced progress write-back.
function MangaReader:_scheduleProgress()
    if self._progress_scheduled then UIManager:unschedule(self._flush_progress_fn) end
    self._flush_progress_fn = self._flush_progress_fn or function() self:_flushProgress() end
    self._progress_scheduled = true
    UIManager:scheduleIn(1.0, self._flush_progress_fn)
end

function MangaReader:_flushProgress()
    self._progress_scheduled = false
    local fn = self.chapters[self.chapter_index]
    self.api:patch("/api/manga/" .. urlencode(self.manga.id),
        { last_read_chapter = fn, last_read_page = self.page })
end

function MangaReader:onClose()
    if self._progress_scheduled then
        UIManager:unschedule(self._flush_progress_fn)
        self:_flushProgress()
    end
    if self.image_widget then self.image_widget:free() end
    self.page_data = nil
    UIManager:close(self)
    -- Tell the chapter list our final position so it can refresh the resume option…
    if self.on_close then
        self.on_close(self.chapters[self.chapter_index], self.page)
    end
    -- …and force a repaint so the list is visible again after the full-screen reader.
    UIManager:setDirty("all", "ui")
    return true
end

-------------------------------------------------------------------------------
-- Cover grid: a paged grid of cover cards for the manga-selection lists.
-- One batch cover fetch per page (HTTP blocks the UI loop), one page of decoded
-- BlitBuffers held at a time. Tapping a card opens that manga's chapter list.
-------------------------------------------------------------------------------

local MangaGrid = InputContainer:extend{
    api = nil,
    manga_list = nil,   -- the matched + sorted array from showList
    title = nil,        -- category name, shown in the top bar
    plugin = nil,       -- MangaLibrary instance (openManga, _untrack)
    page = 1,
    _cards = nil,       -- cover ImageWidgets currently on screen, for :free()
}

function MangaGrid:init()
    self:_computeGeometry()
    local w, h = Screen:getWidth(), Screen:getHeight()
    self.dimen = Geom:new{ x = 0, y = 0, w = w, h = h }
    if Device:isTouchDevice() then
        self.ges_events = {
            TapGrid = { GestureRange:new{ ges = "tap",
                range = Geom:new{ x = 0, y = 0, w = w, h = h } } },
            SwipeNav = { GestureRange:new{ ges = "swipe",
                range = Geom:new{ x = 0, y = 0, w = w, h = h } } },
        }
    end
    if Device:hasKeys() then
        self.key_events = {
            KeyNext = { { Device.input.group.PgFwd } },
            KeyPrev = { { Device.input.group.PgBack } },
            Close = { { "Back" } },
        }
    end
    self._cards = {}
    self[1] = self:_messageFrame(_("Loading covers…"))
    self:_buildPage()
end

-- Derive columns/rows/card size from the screen. Recomputed on every build so
-- rotation is self-correcting. Card width targets a portrait 3-column layout and
-- widens the column count in landscape to keep covers a roughly constant size.
function MangaGrid:_computeGeometry()
    local w, h = Screen:getWidth(), Screen:getHeight()
    self._title_h = Screen:scaleBySize(42)
    self._footer_h = Screen:scaleBySize(28)
    -- Top-right "X" tap target (close to the main categories menu), like other
    -- KOReader menus. Generous hit box so it's easy to land on e-ink.
    self._x_box_w = Screen:scaleBySize(72)
    self._x_box_h = self._title_h + Screen:scaleBySize(8)
    local grid_h = h - self._title_h - self._footer_h
    -- Target a fixed 3x2 grid in portrait (6 cards) for larger covers. Cards fill
    -- the available space and the cover takes whatever height is left after the
    -- text, rather than deriving the row count from a fixed cover ratio.
    local portrait = h >= w
    self.cols = portrait and 3 or 4
    self.rows = 2
    self.per_page = self.cols * self.rows
    self._card_w = math.floor(w / self.cols)
    self._card_h = math.floor(grid_h / self.rows)
    self._cover_w = self._card_w - Screen:scaleBySize(8)  -- small gutter
    -- Titles are long, so use a small font and reserve room for the title to wrap
    -- to two lines (plus one progress line). Measure the real line height of the
    -- chosen face so the reserved block matches and nothing overlaps the next row.
    self._title_face = Font:getFace("xx_smallinfofont")
    local probe = TextWidget:new{ text = "Ag", face = self._title_face }
    local line_h = probe:getSize().h
    probe:free()
    self._title_box_h = line_h * 2                        -- title: up to two lines
    self._progress_h = line_h                             -- progress: one line
    local text_h = self._title_box_h + self._progress_h + Screen:scaleBySize(6)
    -- Cover fills the rest of the card; clamp so it stays positive on short screens.
    self._cover_h = math.max(Screen:scaleBySize(40), self._card_h - text_h)
    -- offsets of the centered grid block, shared with tap-mapping
    self._grid_x0 = math.floor((w - self.cols * self._card_w) / 2)
    self._grid_y0 = self._title_h + math.floor((grid_h - self.rows * self._card_h) / 2)
end

function MangaGrid:total_pages()
    return math.max(1, math.ceil(#self.manga_list / self.per_page))
end

-- Same full-screen centred-text frame the reader uses (loading / error states).
function MangaGrid:_messageFrame(text)
    local w, h = Screen:getWidth(), Screen:getHeight()
    return FrameContainer:new{
        background = Blitbuffer.COLOR_WHITE, bordersize = 0,
        CenterContainer:new{
            dimen = Geom:new{ w = w, h = h },
            TextWidget:new{ text = text, face = Font:getFace("infofont") },
        },
    }
end

function MangaGrid:_reconnectThen(retry)
    self[1] = self:_messageFrame(NetworkMgr:isOnline()
        and _("Retrying…")
        or _("Connection lost — reconnecting Wi-Fi…"))
    UIManager:setDirty(self, "ui")
    UIManager:forceRePaint()
    NetworkMgr:runWhenOnline(function() retry() end)
end

-- Free the current page's decoded covers so only one page lives in RAM at a time.
function MangaGrid:_freeCards()
    if self._cards then
        for _i, iw in ipairs(self._cards) do
            if iw.free then iw:free() end
        end
    end
    self._cards = {}
end

local function gridName(m) return m.alias or m.english_title or m.title end

-- Pull the chapter number out of a chapter filename like "Series - 5.cbz" (the
-- trailing number, allowing decimals like 5.5). Returns a string, or nil.
local function chapterNum(fn)
    if not fn then return nil end
    return fn:gsub("%.cbz$", ""):match("(%d+%.?%d*)%s*$")
end

local function gridProgress(m)
    if m.last_read_chapter then
        local ch = chapterNum(m.last_read_chapter)
        if ch then return T(_("Ch.%1, p.%2"), ch, m.last_read_page or 1) end
        return T(_("p.%1"), m.last_read_page or 1)
    end
    if m.last_chapter_on_disk then return T(_("Ch.%1"), m.last_chapter_on_disk) end
    return ""
end

-- Build one card: cover (or a bordered text placeholder) + title + progress.
function MangaGrid:_buildCard(m, jpeg)
    local cover
    if jpeg then
        local bb = RenderImage:renderImageData(jpeg, #jpeg)
        if bb then
            local iw = ImageWidget:new{
                image = bb,
                image_disposable = true,
                width = self._cover_w,
                height = self._cover_h,
                scale_factor = 0,   -- scale to fit, keep aspect
                center = true,
            }
            self._cards[#self._cards + 1] = iw
            cover = iw
        end
    end
    if not cover then
        -- No cover (missing or undecodable): a bordered box with the wrapped title.
        cover = FrameContainer:new{
            bordersize = Screen:scaleBySize(1),
            margin = 0, padding = 0,
            CenterContainer:new{
                dimen = Geom:new{ w = self._cover_w - Screen:scaleBySize(2),
                                  h = self._cover_h - Screen:scaleBySize(2) },
                TextBoxWidget:new{ text = gridName(m), face = self._title_face,
                                   alignment = "center",
                                   width = self._cover_w - Screen:scaleBySize(10),
                                   height = self._cover_h - Screen:scaleBySize(8) },
            },
        }
    end
    return CenterContainer:new{
        dimen = Geom:new{ w = self._card_w, h = self._card_h },
        VerticalGroup:new{
            align = "center",
            cover,
            -- Title wraps to two lines (clipped beyond), centred, at a fixed height
            -- so a long title can never spill into the row below.
            TextBoxWidget:new{ text = gridName(m), face = self._title_face,
                               alignment = "center",
                               width = self._card_w - Screen:scaleBySize(6),
                               height = self._title_box_h },
            TextWidget:new{ text = gridProgress(m), face = self._title_face,
                            max_width = self._cover_w },
        },
    }
end

function MangaGrid:_buildPage(attempt)
    attempt = attempt or 1
    self:_computeGeometry()
    self:_freeCards()

    local first = (self.page - 1) * self.per_page + 1
    local last = math.min(first + self.per_page - 1, #self.manga_list)

    -- Collect ids worth fetching (skip ones we already know have no thumbnail).
    local ids = {}
    for i = first, last do
        local m = self.manga_list[i]
        if m and m.has_thumbnail then ids[#ids + 1] = m.id end
    end

    local covers = {}
    if #ids > 0 then
        -- Paint a loading frame before the blocking batch fetch so it doesn't look frozen.
        self[1] = self:_messageFrame(_("Loading covers…"))
        UIManager:setDirty(self, "ui")
        UIManager:forceRePaint()
        local got, err = self.api:getCovers(ids, self._cover_w)
        if not got then
            -- Likely Wi-Fi dropped on sleep: reconnect and retry once.
            if attempt == 1 then
                self:_reconnectThen(function() self:_buildPage(2) end)
                return
            end
            -- Still failed: fall through with no covers (text placeholders).
        else
            covers = got
        end
    end

    -- Build cards for the slice, then lay them into fixed rows/cols. The last row
    -- is padded with blanks so the tap-to-cell arithmetic stays a regular grid.
    local cards = {}
    for i = first, last do
        local m = self.manga_list[i]
        cards[#cards + 1] = self:_buildCard(m, covers[m.id])
    end

    local rows_group = VerticalGroup:new{ align = "center" }
    local idx = 1
    for _r = 1, self.rows do
        local row = HorizontalGroup:new{}
        for _c = 1, self.cols do
            if cards[idx] then
                table.insert(row, cards[idx])
            else
                table.insert(row, WidgetContainer:new{
                    dimen = Geom:new{ w = self._card_w, h = self._card_h } })
            end
            idx = idx + 1
        end
        table.insert(rows_group, row)
    end

    local w, h = Screen:getWidth(), Screen:getHeight()
    local grid_h = h - self._title_h - self._footer_h
    self[1] = FrameContainer:new{
        background = Blitbuffer.COLOR_WHITE, bordersize = 0,
        VerticalGroup:new{
            align = "center",
            OverlapGroup:new{
                dimen = Geom:new{ w = w, h = self._title_h },
                CenterContainer:new{
                    dimen = Geom:new{ w = w, h = self._title_h },
                    TextWidget:new{ text = self.title or _("Manga"),
                                    face = Font:getFace("tfont"),
                                    max_width = w - 2 * self._x_box_w },
                },
                RightContainer:new{
                    dimen = Geom:new{ w = w - Screen:scaleBySize(16), h = self._title_h },
                    TextWidget:new{ text = "X", face = Font:getFace("tfont") },
                },
            },
            CenterContainer:new{
                dimen = Geom:new{ w = w, h = grid_h },
                rows_group,
            },
            CenterContainer:new{
                dimen = Geom:new{ w = w, h = self._footer_h },
                TextWidget:new{
                    text = T(_("Page %1 / %2"), self.page, self:total_pages()),
                    face = Font:getFace("x_smallinfofont") },
            },
        },
    }
    UIManager:setDirty(self, "full")   -- full refresh clears e-ink ghosting between pages
end

function MangaGrid:_goPage(n)
    n = math.min(math.max(n, 1), self:total_pages())
    if n == self.page then return end
    self.page = n
    self:_buildPage()
end

function MangaGrid:onTapGrid(_arg, ges)
    local x = (ges and ges.pos and ges.pos.x) or 0
    local y = (ges and ges.pos and ges.pos.y) or 0
    local w = Screen:getWidth()
    -- Top-right "X" → back to the main categories menu.
    if x >= w - self._x_box_w and y < self._x_box_h then
        self.plugin:_goMainMenu(self.api)
        return true
    end
    -- Outside the centered grid block (title bar, footer, side margins) → ignore.
    if x < self._grid_x0 or x >= self._grid_x0 + self.cols * self._card_w then return true end
    if y < self._grid_y0 or y >= self._grid_y0 + self.rows * self._card_h then return true end
    local col = math.floor((x - self._grid_x0) / self._card_w)
    local row = math.floor((y - self._grid_y0) / self._card_h)
    local in_page = row * self.cols + col
    local m = self.manga_list[(self.page - 1) * self.per_page + in_page + 1]
    if m then self.plugin:openManga(self.api, m) end
    return true
end

function MangaGrid:onSwipeNav(_arg, ges)
    local dir = ges and ges.direction
    if dir == "west" then self:_goPage(self.page + 1)
    elseif dir == "east" then self:_goPage(self.page - 1) end
    return true
end

function MangaGrid:onKeyNext() self:_goPage(self.page + 1); return true end
function MangaGrid:onKeyPrev() self:_goPage(self.page - 1); return true end

-- Cleanup runs here so it covers both the Back key (onClose) and a teardown via
-- _closeAll (which calls UIManager:close directly).
function MangaGrid:onCloseWidget()
    self:_freeCards()
    if self.plugin then self.plugin:_untrack(self) end
end

function MangaGrid:onClose()
    UIManager:close(self)
    UIManager:setDirty("all", "ui")   -- repaint the category menu beneath
    return true
end

-------------------------------------------------------------------------------
-- Plugin
-------------------------------------------------------------------------------

local MangaLibrary = WidgetContainer:extend{
    name = "mangalibrary",
}

function MangaLibrary:init()
    self.settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/mangalibrary.lua")
    self.ui.menu:registerToMainMenu(self)
end

function MangaLibrary:getBaseUrl()
    return self.settings:readSetting("base_url") or DEFAULT_BASE_URL
end

function MangaLibrary:getPrefetch()
    return self.settings:readSetting("prefetch_ahead") or 1
end

function MangaLibrary:getCrop()
    local v = self.settings:readSetting("crop_margins")
    if v == nil then return true end   -- default on
    return v
end

-- Cover-grid view for the manga lists (categories/tags). Default on; off falls
-- back to the original text-row list.
function MangaLibrary:getGridEnabled()
    local v = self.settings:readSetting("cover_grid")
    if v == nil then return true end   -- default on
    return v
end

-- Screensaver toggles. The master switch must be on for the plugin to touch the
-- device sleep screen at all; the second chooses the manga's selected cover vs. the
-- current page. Both migrate from the old single "sleep_cover" setting.
function MangaLibrary:getScreensaverEnabled()
    local v = self.settings:readSetting("screensaver_enabled")
    if v ~= nil then return v end
    local old = self.settings:readSetting("sleep_cover")
    if old == nil then return true end   -- preserve the old default (on)
    return old
end

function MangaLibrary:getScreensaverUseCover()
    local v = self.settings:readSetting("screensaver_use_cover")
    if v ~= nil then return v end
    return true   -- when enabled, default to the selected cover
end

function MangaLibrary:addToMainMenu(menu_items)
    menu_items.manga_library = {
        text = _("Manga Library"),
        sorting_hint = "tools",
        sub_item_table = {
            {
                text = _("Open library"),
                callback = function() self:openLibrary() end,
            },
            {
                text = _("Test connection"),
                keep_menu_open = true,
                callback = function() self:testConnection() end,
            },
            {
                text_func = function() return T(_("Server: %1"), self:getBaseUrl()) end,
                keep_menu_open = true,
                callback = function() self:editServer() end,
            },
            {
                text_func = function()
                    return T(_("Preload pages ahead: %1"), self:getPrefetch())
                end,
                sub_item_table = {
                    self:_prefetchOption(0),
                    self:_prefetchOption(1),
                    self:_prefetchOption(2),
                },
            },
            {
                text = _("Crop page margins"),
                checked_func = function() return self:getCrop() end,
                callback = function()
                    self.settings:saveSetting("crop_margins", not self:getCrop())
                    self.settings:flush()
                end,
            },
            {
                text = _("Cover grid (off: text list)"),
                checked_func = function() return self:getGridEnabled() end,
                callback = function()
                    self.settings:saveSetting("cover_grid", not self:getGridEnabled())
                    self.settings:flush()
                end,
            },
            {
                text = _("Use as screensaver"),
                checked_func = function() return self:getScreensaverEnabled() end,
                callback = function()
                    local on = not self:getScreensaverEnabled()
                    self.settings:saveSetting("screensaver_enabled", on)
                    self.settings:flush()
                    -- Turning the master switch off restores the user's own
                    -- screensaver right away if a reader had overridden it.
                    if not on then self:_restoreScreensaver() end
                end,
            },
            {
                text = _("Use cover as screensaver (off: use current page)"),
                enabled_func = function() return self:getScreensaverEnabled() end,
                checked_func = function() return self:getScreensaverUseCover() end,
                callback = function()
                    self.settings:saveSetting("screensaver_use_cover", not self:getScreensaverUseCover())
                    self.settings:flush()
                end,
            },
        },
    }
end

function MangaLibrary:_prefetchOption(n)
    return {
        text = tostring(n),
        checked_func = function() return self:getPrefetch() == n end,
        callback = function() self.settings:saveSetting("prefetch_ahead", n); self.settings:flush() end,
        radio = true,
    }
end

function MangaLibrary:editServer()
    local input
    input = InputDialog:new{
        title = _("Manga server address"),
        input = self:getBaseUrl(),
        buttons = {{
            { text = _("Cancel"), callback = function() UIManager:close(input) end },
            { text = _("Save"), is_enter_default = true, callback = function()
                local v = input:getInputText():gsub("%s+", "")
                UIManager:close(input)
                if v ~= "" then
                    self.settings:saveSetting("base_url", v)
                    self.settings:flush()
                end
            end },
        }},
    }
    UIManager:show(input)
    input:onShowKeyboard()
end

-- Run an action only once WiFi is up.
function MangaLibrary:_online(action)
    NetworkMgr:runWhenOnline(action)
end

-- Ensure a server address is configured; if not, prompt for it and return false.
function MangaLibrary:_haveServer()
    local url = self:getBaseUrl()
    if url and url ~= "" then return true end
    UIManager:show(InfoMessage:new{
        text = _("No server set yet.\nEnter your manga server address (e.g. http://192.168.0.x:8684).") })
    self:editServer()
    return false
end

function MangaLibrary:testConnection()
    if not self:_haveServer() then return end
    self:_online(function()
        local url = self:getBaseUrl()
        local api = MangaApi.new(url)
        UIManager:show(InfoMessage:new{ text = _("Testing…"), timeout = 1 })
        UIManager:forceRePaint()
        local res, err = api:getJson("/api/manga")
        local msg
        if res then
            msg = T(_("Connected.\n\nServer: %1\nTitles: %2"), url, #res)
        else
            msg = T(_("Could not reach the server.\n\nServer: %1\nError: %2\n\n%3"),
                url, err or _("unknown"), self:_hint(err))
        end
        UIManager:show(InfoMessage:new{ text = msg })
    end)
end

-- Translate a raw socket/HTTP error into a plain-language hint.
function MangaLibrary:_hint(err)
    err = tostring(err or "")
    if err:find("HTTP 403") then
        return _("403 = the Kobo's IP is blocked by the reverse proxy. Add its WiFi IP to the Caddy allow-list.")
    elseif err:find("HTTP 404") then
        return _("404 = reached the server but the path is wrong. Check the URL has no trailing path.")
    elseif err:lower():find("host or service not provided") or err:lower():find("not found")
        or err:lower():find("name or service") or err:lower():find("resolve") then
        return _("Looks like DNS: the Kobo can't resolve the hostname. Try a plain IP, e.g. http://192.168.x.x:8684")
    elseif err:lower():find("ssl") or err:lower():find("tls") or err:lower():find("handshake")
        or err:lower():find("certificate") then
        return _("Looks like TLS. Try the plain-HTTP LAN address instead, e.g. http://192.168.x.x:8684")
    elseif err:lower():find("timeout") then
        return _("Timed out — the Kobo may not be on the same network as the server.")
    elseif err:lower():find("refused") then
        return _("Connection refused — wrong port, or the backend isn't running.")
    end
    return _("Try the plain-HTTP LAN address to rule out DNS/TLS, e.g. http://192.168.x.x:8684")
end

function MangaLibrary:openLibrary()
    if not self:_haveServer() then return end
    self:_online(function()
        local api = MangaApi.new(self:getBaseUrl())
        local list, err = api:getJson("/api/manga")
        if not list then
            UIManager:show(InfoMessage:new{ text = T(
                _("Could not reach the manga server.\n\nServer: %1\nError: %2\n\n%3"),
                self:getBaseUrl(), err or _("unknown"), self:_hint(err)) })
            return
        end
        self._library = list
        self:showFilterMenu(api)
    end)
end

function MangaLibrary:showFilterMenu(api)
    local menu
    local function build()
        local items = {}

        -- Jump straight back into the most recently read page (tracked on the device).
        local last = self.settings:readSetting("last_read")
        if last and last.id then
            table.insert(items, {
                text = T(_("Continue: %1 — %2 (p.%3)"),
                    last.title or "?", (last.chapter or ""):gsub("%.cbz$", ""), last.page or 1),
                callback = function() self:continueReading(api, last) end,
            })
        end

        -- The library is a per-session snapshot; this re-pulls it so external
        -- changes (e.g. marked read / progress cleared in the webapp) show up.
        table.insert(items, { text = _("Reload from server"), callback = function()
            -- Connect Wi-Fi first if the device is offline, then re-pull.
            self:_online(function()
                local list, err = api:getJson("/api/manga")
                if list then
                    self._library = list
                    menu:switchItemTable(_("Manga Library"), build())
                else
                    UIManager:show(InfoMessage:new{
                        text = T(_("Reload failed: %1"), err or "?"), timeout = 3 })
                end
            end)
        end })

        for _i, f in ipairs(FILTERS) do
            local key = f.key
            local count = 0
            for _j, m in ipairs(self._library) do
                if matchesFilter(m, key) then count = count + 1 end
            end
            local sort_fn = f.recent and byRecent or nil
            table.insert(items, {
                text = f.text,
                mandatory = tostring(count),
                callback = function() self:showList(api, f.text, function(m) return matchesFilter(m, key) end, sort_fn) end,
            })
        end
        table.insert(items, {
            text = _("Browse by tag"),
            callback = function() self:showTagMenu(api) end,
        })
        table.insert(items, {
            text = _("Connect Wi-Fi"),
            callback = function()
                if NetworkMgr:isOnline() then
                    UIManager:show(InfoMessage:new{ text = _("Wi-Fi is connected."), timeout = 2 })
                else
                    UIManager:show(InfoMessage:new{ text = _("Connecting Wi-Fi…"), timeout = 2 })
                    NetworkMgr:runWhenOnline(function()
                        UIManager:show(InfoMessage:new{ text = _("Wi-Fi connected."), timeout = 2 })
                    end)
                end
            end,
        })
        return items
    end
    menu = self:_showMenu(_("Manga Library"), build())
end

function MangaLibrary:showTagMenu(api)
    local tags = api:getJson("/api/tags")
    if not tags then
        UIManager:show(InfoMessage:new{ text = _("Could not load tags.") })
        return
    end
    local items = {}
    for _i, t in ipairs(tags) do
        local tag = t.tag
        table.insert(items, {
            text = tag,
            mandatory = tostring(t.count),
            callback = function()
                self:showList(api, tag, function(m)
                    if m.hidden then return false end
                    for _j, mt in ipairs(m.tags or {}) do if mt == tag then return true end end
                    return false
                end)
            end,
        })
    end
    self:_showMenu(_("Browse by tag"), items)
end

function MangaLibrary:showList(api, title, predicate, sort_fn)
    local matched = {}
    for _i, m in ipairs(self._library) do
        if predicate(m) then matched[#matched + 1] = m end
    end
    if sort_fn then table.sort(matched, sort_fn) end
    if #matched == 0 then
        UIManager:show(InfoMessage:new{ text = _("Nothing here yet.") })
        return
    end
    if self:getGridEnabled() then
        self:_showGrid(api, title, matched)
    else
        self:_showListRows(api, title, matched)
    end
end

-- The original text-row view, kept verbatim as the fallback when the cover grid
-- is turned off.
function MangaLibrary:_showListRows(api, title, matched)
    local items = {}
    for _i, m in ipairs(matched) do
        local name = m.alias or m.english_title or m.title
        local mandatory
        if m.last_read_chapter then
            mandatory = T(_("p.%1"), m.last_read_page or 1)
        elseif m.last_chapter_on_disk then
            mandatory = T(_("Ch.%1"), m.last_chapter_on_disk)
        end
        table.insert(items, {
            text = name,
            mandatory = mandatory,
            callback = function() self:openManga(api, m) end,
        })
    end
    self:_showMenu(title, items)
end

-- Cover-grid view. Tracked in self._menus like a menu so _closeAll tears it down.
function MangaLibrary:_showGrid(api, title, matched)
    self._menus = self._menus or {}
    local grid = MangaGrid:new{
        api = api, title = title, manga_list = matched, plugin = self,
    }
    UIManager:show(grid)
    table.insert(self._menus, grid)
    return grid
end

function MangaLibrary:openManga(api, m)
    local detail = api:getJson("/api/manga/" .. urlencode(m.id))
    if not detail or not detail.chapters or #detail.chapters == 0 then
        UIManager:show(InfoMessage:new{ text = _("No chapters available.") })
        return
    end
    local chapters = detail.chapters  -- ascending order from backend
    local title = detail.alias or detail.english_title or detail.title
    local menu

    -- Build the chapter item list from detail's *current* progress, so it can be
    -- rebuilt after reading to reflect the new resume point.
    local function build_items()
        local items = {}
        if detail.last_read_chapter then
            for idx, fn in ipairs(chapters) do
                if fn == detail.last_read_chapter then
                    items[#items + 1] = {
                        text = T(_("Continue: %1 (p.%2)"),
                            fn:gsub("%.cbz$", ""), detail.last_read_page or 1),
                        callback = function()
                            self:openReader(api, detail, chapters, idx, detail.last_read_page or 1, menu)
                        end,
                    }
                    break
                end
            end
        end
        -- chapters newest first, like the webapp
        for idx = #chapters, 1, -1 do
            local fn = chapters[idx]
            local mandatory
            if fn == detail.last_read_chapter then mandatory = T(_("p.%1"), detail.last_read_page or 1) end
            local resume_page = (fn == detail.last_read_chapter) and (detail.last_read_page or 1) or 1
            items[#items + 1] = {
                text = fn:gsub("%.cbz$", ""),
                mandatory = mandatory,
                callback = function()
                    -- Only the last-read chapter has a saved page to resume from; any
                    -- other chapter has nothing to resume, so start at page 1.
                    if resume_page > 1 then
                        self:_chooseStart(api, detail, chapters, idx, resume_page, menu)
                    else
                        self:openReader(api, detail, chapters, idx, 1, menu)
                    end
                end,
            }
        end
        return items
    end

    menu = self:_showMenu(title, build_items())
    -- Let the menu rebuild itself (used by the reader after progress changes).
    menu._rebuild = function() menu:switchItemTable(title, build_items()) end
end

-- Ask whether to resume or restart a chapter that has a saved page.
function MangaLibrary:_chooseStart(api, detail, chapters, idx, resume_page, menu)
    local dialog
    dialog = ButtonDialog:new{
        title = T(_("%1\nSaved at page %2"), chapters[idx]:gsub("%.cbz$", ""), resume_page),
        title_align = "center",
        buttons = {
            {{ text = T(_("Resume at page %1"), resume_page), callback = function()
                UIManager:close(dialog)
                self:openReader(api, detail, chapters, idx, resume_page, menu)
            end }},
            {{ text = _("Start from beginning"), callback = function()
                UIManager:close(dialog)
                self:openReader(api, detail, chapters, idx, 1, menu)
            end }},
        },
    }
    UIManager:show(dialog)
end

function MangaLibrary:openReader(api, manga, chapters, chapter_index, start_page, menu)
    -- Reset per-title screensaver state before the reader renders its first page.
    -- As pages render the reader calls onReaderPage(), which sets the cover (once)
    -- or the current page per the two screensaver toggles. Nothing is touched unless
    -- the master toggle is on.
    self._ss_cover_done = false
    local reader = MangaReader:new{
        api = api,
        manga = manga,
        chapters = chapters,
        chapter_index = chapter_index,
        page = start_page or 1,
        prefetch_ahead = self:getPrefetch(),
        crop = self:getCrop(),
        plugin = self,
        -- Called when the reader closes: sync caches and rebuild the chapter list so
        -- the new resume point shows immediately.
        on_close = function(last_chapter, last_page)
            manga.last_read_chapter = last_chapter
            manga.last_read_page = last_page
            self:_syncLibrary(manga.id, last_chapter, last_page)
            self:_recordLastRead(manga, last_chapter, last_page)
            self:_restoreScreensaver()
            if menu and menu._rebuild then menu._rebuild() end
        end,
    }
    UIManager:show(reader)
end

-- Called by the reader as each page renders. Points the device sleep screen at
-- either the manga's selected cover (once per title) or the current page, per the
-- two screensaver toggles. KOReader's own "book cover" screensaver reads the open
-- *document*; this plugin renders pages itself with no document open, so we set an
-- explicit image file instead.
function MangaLibrary:onReaderPage(api, manga, page_data)
    if not self:getScreensaverEnabled() then return end
    if self:getScreensaverUseCover() then
        -- Selected cover: set it ONCE per title (on nextTick so it never delays the
        -- first paint) and leave it. Page images are never written in this mode.
        if self._ss_cover_done then return end
        self._ss_cover_done = true
        UIManager:nextTick(function()
            if manga and manga.id then
                self:_useImageScreensaver(api:getBytes("/cover/" .. urlencode(manga.id)))
            end
        end)
    else
        -- Current page: the already-rendered JPEG bytes, refreshed on each turn.
        self:_useImageScreensaver(page_data)
    end
end

-- Write JPEG bytes to our sleep-screen file and point KOReader's screensaver at it,
-- remembering the user's real screensaver settings the first time so we can restore
-- them when reading ends. KOReader has no "image file" screensaver type; the way to
-- show an arbitrary image is type "document_cover" with screensaver_document_cover
-- pointing at it (KOReader detects it's an image file and shows it directly).
function MangaLibrary:_useImageScreensaver(data)
    if not data or #data == 0 then return end   -- nothing to show; leave sleep screen alone
    local path = DataStorage:getSettingsDir() .. "/mangalibrary_sleep_cover.jpg"
    local f = io.open(path, "wb")
    if not f then return end
    f:write(data)
    f:close()
    -- Capture the user's real setting once (guard against re-capturing our own value
    -- if a reader is opened again before the previous one restored).
    if not self._saved_ss then
        self._saved_ss = {
            type = G_reader_settings:readSetting("screensaver_type"),
            cover = G_reader_settings:readSetting("screensaver_document_cover"),
        }
    end
    G_reader_settings:saveSetting("screensaver_type", "document_cover")
    G_reader_settings:saveSetting("screensaver_document_cover", path)
end

-- Put the user's pre-reading screensaver settings back.
function MangaLibrary:_restoreScreensaver()
    if not self._saved_ss then return end
    G_reader_settings:saveSetting("screensaver_type", self._saved_ss.type)
    G_reader_settings:saveSetting("screensaver_document_cover", self._saved_ss.cover)
    self._saved_ss = nil
end

-- Remember the most recently read manga/chapter/page on the device, for the
-- "Continue" shortcut on the categories menu.
function MangaLibrary:_recordLastRead(manga, chapter, page)
    self.settings:saveSetting("last_read", {
        id = manga.id,
        title = manga.alias or manga.english_title or manga.title,
        chapter = chapter,
        page = page,
    })
    self.settings:flush()
end

-- Open the reader directly on the saved last-read manga/chapter/page.
function MangaLibrary:continueReading(api, last)
    self:_online(function()
        local detail = api:getJson("/api/manga/" .. urlencode(last.id))
        if not detail or not detail.chapters or #detail.chapters == 0 then
            UIManager:show(InfoMessage:new{ text = _("Could not open last read."), timeout = 3 })
            return
        end
        local chapters = detail.chapters
        local idx = 1
        for i, fn in ipairs(chapters) do
            if fn == last.chapter then idx = i; break end
        end
        self:openReader(api, detail, chapters, idx, last.page or 1, nil)
    end)
end

function MangaLibrary:_showMenu(title, items)
    self._menus = self._menus or {}
    local menu
    menu = Menu:new{
        title = title,
        item_table = items,
        is_borderless = true,
        is_popout = false,
        width = Screen:getWidth(),
        height = Screen:getHeight(),
        onMenuSelect = function(_self, item)
            if item.callback then item.callback() end
        end,
        -- drop ourselves from the tracked stack when closed (e.g. via Back)
        close_callback = function()
            for i, m in ipairs(self._menus) do
                if m == menu then table.remove(self._menus, i); break end
            end
        end,
    }
    UIManager:show(menu)
    table.insert(self._menus, menu)
    return menu
end

-- Drop a tracked widget (menu or grid) from the stack. Tolerant: a no-op if it's
-- already gone, so it's safe to call during _closeAll teardown.
function MangaLibrary:_untrack(widget)
    for i, m in ipairs(self._menus or {}) do
        if m == widget then table.remove(self._menus, i); break end
    end
end

-- Close every plugin menu we've opened (used by "Close app" and "Main Menu").
function MangaLibrary:_closeAll()
    local menus = self._menus or {}
    self._menus = {}   -- reset first so each close_callback is a no-op during teardown
    for i = #menus, 1, -1 do
        UIManager:close(menus[i])
    end
end

-- Tear down to a single fresh categories menu.
function MangaLibrary:_goMainMenu(api)
    self:_closeAll()
    self:showFilterMenu(api)
end

-- Keep the in-memory library list in sync with progress written from the reader,
-- so filter views (Reading, etc.) reflect it without a full reload.
function MangaLibrary:_syncLibrary(id, chapter, page)
    if not self._library then return end
    for _i, m in ipairs(self._library) do
        if m.id == id then
            m.last_read_chapter = chapter
            m.last_read_page = page
            -- Stamp locally (UTC, matching the server) so the Last Read view orders
            -- this title to the top without waiting for a reload.
            m.last_read_at = os.date("!%Y-%m-%d %H:%M:%S")
            return
        end
    end
end

return MangaLibrary
