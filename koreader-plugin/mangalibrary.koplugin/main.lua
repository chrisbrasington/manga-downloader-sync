--[[
Manga Library — KOReader plugin

Browses and reads manga served by the manga-ereader-backend container
(manga-api.home.chrisincode.com). All content is fetched over WiFi; pages
arrive as pre-rendered grayscale JPEGs sized for the device. Reading progress
is written back to the shared manga.db so the browser webapp and the Kobo
stay in sync.
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
local TextWidget = require("ui/widget/textwidget")
local Menu = require("ui/widget/menu")
local InfoMessage = require("ui/widget/infomessage")
local InputDialog = require("ui/widget/inputdialog")
local ButtonDialog = require("ui/widget/buttondialog")
local GestureRange = require("ui/gesturerange")
local Geom = require("ui/geometry")
local Font = require("ui/font")
local Blitbuffer = require("ffi/blitbuffer")
local NetworkMgr = require("ui/network/manager")
local DataStorage = require("datastorage")
local LuaSettings = require("luasettings")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
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

local CACHE_DIR = DataStorage:getDataDir() .. "/cache/mangalibrary"
local DEFAULT_BASE_URL = "http://192.168.0.11:8684"

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

-- Recursive mkdir (lfs.mkdir only creates one level).
local function mkdir_p(path)
    local cur = ""
    for part in path:gmatch("[^/]+") do
        cur = cur .. "/" .. part
        if lfs.attributes(cur, "mode") ~= "directory" then
            lfs.mkdir(cur)
        end
    end
end

-- The nine webapp library filters, plus tag browsing, mirrored here.
local FILTERS = {
    { key = "all",         text = _("All") },
    { key = "favorites",   text = _("\u{2B50} Favorites") },
    { key = "reading",     text = _("\u{1F4D6} Reading") },
    { key = "downloading", text = _("\u{1F4E5} Downloading") },
    { key = "completed",   text = _("Completed") },
    { key = "hiatus",      text = _("Hiatus") },
    { key = "archived",    text = _("Archived") },
    { key = "read",        text = _("\u{2713} Read") },
    { key = "hidden",      text = _("\u{1F441} Hidden") },
}

local function matchesFilter(m, key)
    if key == "all" then return not m.hidden end
    if key == "favorites" then return m.favorited and not m.hidden end
    if key == "reading" then return m.last_read_chapter ~= nil and not m.hidden end
    if key == "downloading" then return m.download_enabled and not m.hidden end
    if key == "completed" then return m.status == "completed" and not m.hidden end
    if key == "hiatus" then return m.status == "hiatus" and not m.hidden end
    if key == "archived" then return m.status == "archived" and not m.hidden end
    if key == "read" then return m.read and not m.hidden end
    if key == "hidden" then return m.hidden end
    return true
end

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

function MangaApi:_request(method, path, body_tbl, sink_file)
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
    local sink, result_tbl, out_file
    if sink_file then
        out_file = io.open(sink_file .. ".part", "w")
        if not out_file then return nil, "cannot open cache file" end
        sink = ltn12.sink.file(out_file)
    else
        result_tbl = {}
        sink = ltn12.sink.table(result_tbl)
    end

    local req = { url = url, method = method, headers = headers, source = source, sink = sink }
    if requester == https.request then
        -- Be permissive so a self-hosted cert / modern TLS negotiates cleanly.
        req.protocol = "any"
        req.options = "all"
        req.verify = "none"
    end

    socketutil:set_timeout(10, 30)
    -- table form returns (1, code, headers, status) on success, (nil, err) on failure
    local ok, code = requester(req)
    socketutil:reset_timeout()
    if out_file then pcall(function() out_file:close() end) end

    if ok == nil then
        -- socket-level failure: DNS, connection refused, TLS handshake, timeout…
        if sink_file then os.remove(sink_file .. ".part") end
        return nil, tostring(code)
    end
    if code ~= 200 then
        if sink_file then os.remove(sink_file .. ".part") end
        return nil, "HTTP " .. tostring(code)
    end

    if sink_file then
        if os.rename(sink_file .. ".part", sink_file) then return true end
        return nil, "cache write failed"
    end
    local decoded = rapidjson.decode(table.concat(result_tbl))
    if decoded == nil then return nil, "invalid JSON from server" end
    return denull(decoded)
end

function MangaApi:getJson(path) return self:_request("GET", path) end

function MangaApi:patch(path, tbl) return self:_request("PATCH", path, tbl) end

function MangaApi:downloadTo(path, dest_file) return self:_request("GET", path, nil, dest_file) end

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
    page_width = nil,
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

function MangaReader:_chapterDir()
    return CACHE_DIR .. "/" .. self.manga.id .. "/" .. self.chapter_index
end

function MangaReader:_chapterCacheDir()
    mkdir_p(self:_chapterDir())
end

function MangaReader:_pageFile(n)
    return self:_chapterDir() .. "/" .. n .. "_" .. self.page_width .. ".jpg"
end

function MangaReader:_pagePath(n)
    local fn = self.chapters[self.chapter_index]
    return T("/cbz/%1/%2/%3?w=%4", urlencode(self.manga.id), urlencode(fn), n, self.page_width)
end

-- Ensure page n is on disk; returns local file path or nil.
function MangaReader:_ensurePage(n)
    if n < 1 or (self.total_pages > 0 and n > self.total_pages) then return nil end
    local file = self:_pageFile(n)
    if lfs.attributes(file, "mode") == "file" then return file end
    local ok = self.api:downloadTo(self:_pagePath(n), file)
    if ok then return file end
    return nil
end

function MangaReader:_evict(keep_from, keep_to)
    local dir = self:_chapterDir()
    for f in lfs.dir(dir) do
        local n = tonumber(f:match("^(%d+)_"))
        if n and (n < keep_from or n > keep_to) then
            os.remove(dir .. "/" .. f)
        end
    end
end

function MangaReader:loadChapter(idx, start_page)
    if idx < 1 or idx > #self.chapters then return end
    self.chapter_index = idx
    self:_chapterCacheDir()
    local fn = self.chapters[idx]
    local info = self.api:getJson(T("/cbz/%1/%2/info", urlencode(self.manga.id), urlencode(fn)))
    self.total_pages = (info and info.page_count) or 0
    if self.total_pages == 0 then
        self[1] = self:_messageFrame(_("Could not load this chapter."))
        UIManager:setDirty(self, "ui")
        UIManager:show(InfoMessage:new{ text = _("Could not load this chapter."), timeout = 3 })
        return
    end
    self:setPage(math.min(math.max(start_page or 1, 1), self.total_pages))
end

function MangaReader:setPage(n)
    self.page = n
    local loading
    local file = self:_pageFile(n)
    if lfs.attributes(file, "mode") ~= "file" then
        loading = InfoMessage:new{ text = _("Loading…") }
        UIManager:show(loading)
        UIManager:forceRePaint()
    end
    file = self:_ensurePage(n)
    if loading then UIManager:close(loading) end
    if not file then
        self.page = math.max(1, math.min(n, self.total_pages)) -- keep state consistent
        self[1] = self:_messageFrame(T(_("Failed to load page %1."), n))
        UIManager:setDirty(self, "ui")
        UIManager:show(InfoMessage:new{
            text = T(_("Failed to load page %1."), n), timeout = 3 })
        return
    end

    if self.image_widget then self.image_widget:free() end
    self.image_widget = ImageWidget:new{
        file = file,
        width = Screen:getWidth(),
        height = Screen:getHeight() - self.footer_height(),
        scale_factor = 0,   -- scale to fit, keep aspect
        center = true,
    }
    local footer = self:_buildFooter()
    self[1] = FrameContainer:new{
        background = Blitbuffer.COLOR_WHITE,
        bordersize = 0,
        VerticalGroup:new{
            CenterContainer:new{
                dimen = Geom:new{ w = Screen:getWidth(), h = Screen:getHeight() - self.footer_height() },
                self.image_widget,
            },
            footer,
        },
    }
    UIManager:setDirty(self, "full")
    self:_scheduleProgress()

    -- prefetch ahead, after this page paints
    self:_evict(n - 1, n + self.prefetch_ahead + 1)
    if self.prefetch_ahead > 0 then
        UIManager:scheduleIn(0.15, function()
            for i = 1, self.prefetch_ahead do self:_ensurePage(n + i) end
        end)
    end
end

function MangaReader.footer_height() return 34 end

function MangaReader:_buildFooter()
    local label = T(_("%1   ·   p. %2 / %3"),
        self.chapters[self.chapter_index]:gsub("%.cbz$", ""), self.page, self.total_pages)
    return FrameContainer:new{
        background = Blitbuffer.COLOR_WHITE,
        bordersize = 0,
        width = Screen:getWidth(),
        height = self.footer_height(),
        CenterContainer:new{
            dimen = Geom:new{ w = Screen:getWidth(), h = self.footer_height() },
            TextWidget:new{ text = label, face = Font:getFace("xx_smallinfofont") },
        },
    }
end

function MangaReader:onTapNext() self:nextPage(); return true end
function MangaReader:onTapPrev() self:prevPage(); return true end
function MangaReader:onKeyNext() self:nextPage(); return true end
function MangaReader:onKeyPrev() self:prevPage(); return true end

-- Swipe to page; consume every swipe so the modal reader doesn't leak gestures.
function MangaReader:onSwipeNav(_arg, ges)
    local dir = ges and ges.direction
    if dir == "west" then
        self:nextPage()
    elseif dir == "east" then
        self:prevPage()
    end
    return true
end

function MangaReader:nextPage()
    if self.page < self.total_pages then
        self:setPage(self.page + 1)
    elseif self.chapter_index < #self.chapters then
        self:loadChapter(self.chapter_index + 1, 1)
    else
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
        buttons = {
            {{ text = _("Previous chapter"), enabled = self.chapter_index > 1, callback = function()
                UIManager:close(dialog); self:loadChapter(self.chapter_index - 1, 1) end }},
            {{ text = _("Next chapter"), enabled = self.chapter_index < #self.chapters, callback = function()
                UIManager:close(dialog); self:loadChapter(self.chapter_index + 1, 1) end }},
            {{ text = _("Go to page…"), callback = function()
                UIManager:close(dialog); self:_goToPage() end }},
            {{ text = _("Close reader"), callback = function()
                UIManager:close(dialog); self:onClose() end }},
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
    UIManager:close(self)
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

function MangaLibrary:testConnection()
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
    local items = {}
    for _i, f in ipairs(FILTERS) do
        local key = f.key
        local count = 0
        for _j, m in ipairs(self._library) do
            if matchesFilter(m, key) then count = count + 1 end
        end
        table.insert(items, {
            text = f.text,
            mandatory = tostring(count),
            callback = function() self:showList(api, f.text, function(m) return matchesFilter(m, key) end) end,
        })
    end
    table.insert(items, {
        text = _("\u{1F516} Browse by tag"),
        callback = function() self:showTagMenu(api) end,
    })
    self:_showMenu(_("Manga Library"), items)
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

function MangaLibrary:showList(api, title, predicate)
    local items = {}
    for _i, m in ipairs(self._library) do
        if predicate(m) then
            local name = m.alias or m.english_title or m.title
            local mandatory
            if m.last_read_chapter then
                mandatory = T(_("\u{25B6} p.%1"), m.last_read_page or 1)
            elseif m.last_chapter_on_disk then
                mandatory = T(_("Ch.%1"), m.last_chapter_on_disk)
            end
            table.insert(items, {
                text = name,
                mandatory = mandatory,
                callback = function() self:openManga(api, m) end,
            })
        end
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
    local items = {}
    -- "Continue" shortcut at top if there is saved progress
    if detail.last_read_chapter then
        for idx, fn in ipairs(chapters) do
            if fn == detail.last_read_chapter then
                items[#items + 1] = {
                    text = T(_("\u{25B6} Continue: %1 (p.%2)"),
                        fn:gsub("%.cbz$", ""), detail.last_read_page or 1),
                    callback = function() self:openReader(api, detail, chapters, idx, detail.last_read_page or 1) end,
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
                -- Only the last-read chapter has a saved page to resume from; for any
                -- other chapter there is nothing to resume, so just start at page 1.
                if resume_page > 1 then
                    self:_chooseStart(api, detail, chapters, idx, resume_page)
                else
                    self:openReader(api, detail, chapters, idx, 1)
                end
            end,
        }
    end
    self:_showMenu(detail.alias or detail.english_title or detail.title, items)
end

-- Ask whether to resume or restart a chapter that has a saved page.
function MangaLibrary:_chooseStart(api, detail, chapters, idx, resume_page)
    local dialog
    dialog = ButtonDialog:new{
        title = T(_("%1\nSaved at page %2"), chapters[idx]:gsub("%.cbz$", ""), resume_page),
        title_align = "center",
        buttons = {
            {{ text = T(_("Resume at page %1"), resume_page), callback = function()
                UIManager:close(dialog)
                self:openReader(api, detail, chapters, idx, resume_page)
            end }},
            {{ text = _("Start from beginning"), callback = function()
                UIManager:close(dialog)
                self:openReader(api, detail, chapters, idx, 1)
            end }},
        },
    }
    UIManager:show(dialog)
end

function MangaLibrary:openReader(api, manga, chapters, chapter_index, start_page)
    local reader = MangaReader:new{
        api = api,
        manga = manga,
        chapters = chapters,
        chapter_index = chapter_index,
        page = start_page or 1,
        prefetch_ahead = self:getPrefetch(),
    }
    UIManager:show(reader)
end

function MangaLibrary:_showMenu(title, items)
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
        close_callback = function() end,
    }
    UIManager:show(menu)
end

return MangaLibrary
