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
local VerticalGroup = require("ui/widget/verticalgroup")
local ImageWidget = require("ui/widget/imagewidget")
local ImageViewer = require("ui/widget/imageviewer")
local RenderImage = require("ui/renderimage")
local ProgressWidget = require("ui/widget/progresswidget")
local TextWidget = require("ui/widget/textwidget")
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
            {{ text = _("Previous chapter"), enabled = self.chapter_index > 1, callback = function()
                UIManager:close(dialog); self:loadChapter(self.chapter_index - 1, 1) end }},
            {{ text = _("Next chapter"), enabled = self.chapter_index < #self.chapters, callback = function()
                UIManager:close(dialog); self:loadChapter(self.chapter_index + 1, 1) end }},
            {{ text = _("Go to page…"), callback = function()
                UIManager:close(dialog); self:_goToPage() end }},
            {{ text = _("Close Chapter"), callback = function()
                UIManager:close(dialog); self:onClose() end }},
            {{ text = _("Main Menu"), callback = function()
                UIManager:close(dialog); self:onClose()
                if self.plugin then self.plugin:_goMainMenu(self.api) end end }},
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
    if #items == 0 then
        UIManager:show(InfoMessage:new{ text = _("Nothing here yet.") })
        return
    end
    self:_showMenu(title, items)
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
