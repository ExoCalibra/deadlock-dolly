// Windows CI exercises the real DX11 overlay on WARP with synthetic editor
// state. No Deadlock modules, private addresses, injection, or console needed.
#include "dolly_overlay.hpp"
#include "dolly_editor.hpp"
#include "dolly_lite.hpp"
#include "dolly_replay_events.hpp"
#include "../src/dolly_ui_tokens_generated.hpp"
#include "dolly_bone_picker.hpp"
#include "dolly_object_picker.hpp"
#include "dolly_renderer_diagnostics.hpp"
#include "dolly_visualization_runtime.hpp"
#include "dolly_reshade.hpp"
#include "dolly_media.hpp"
#include "dolly_video.hpp"
#include "MinHook.h"
#include "imgui.h"
#include "imgui_internal.h"
#include "../src/dolly_overlay_panel.hpp"
#include <d3d11.h>
#include <dxgi.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <vector>
#include <string>
#include <fstream>
#include <algorithm>

static ImGuiContext* screenshot_context = nullptr;
namespace {
bool available = false;
bool shader_loading_stub = false;
bool replay_info_known_stub = true;
std::uint32_t camera_revision_stub = 7;
double camera_time_bias_stub = 0;
unsigned camera_first_stub = 0;
HWND attached = nullptr;
dolly::EditorSnapshot snapshot;
bool observed_mouse_down[5]{};
bool present_keeps_os_cursor = false;
struct ObservedAction {
    dolly::EditorAction action;
    double value, revision, time;
    dolly::CameraPose pose{};
};
std::vector<ObservedAction> observed_actions;
void require(bool condition, const char* message) {
    if (!condition)
        throw std::runtime_error(message);
}

void append_u32(std::vector<unsigned char>& out, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i)
        out.push_back(static_cast<unsigned char>(value >> (8 * i)));
}
void append_double(std::vector<unsigned char>& out, double value) {
    std::uint64_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    for (unsigned i = 0; i < 8; ++i)
        out.push_back(static_cast<unsigned char>(bits >> (8 * i)));
}
std::vector<unsigned char> viewer_packet() {
    // These two synthetic cameras project to the right of the panel. Their
    // connecting segment and glyphs must remain visible in paused flight.
    const dolly::CameraPose a{100, -60, 0, 0, 0, 0, 4.0 / 3.0};
    const dolly::CameraPose b{100, -90, 15, 0, 0, 0, 4.0 / 3.0};
    std::vector<unsigned char> path{'D', 'L', 'Y', 'P', 'A', 'T', 'H', 0};
    append_u32(path, 1);
    append_u32(path, 1);
    append_u32(path, 7);
    append_u32(path, 0);
    append_double(path, 3);
    append_double(path, 0);
    append_double(path, 3);
    for (double value : a)
        append_double(path, value);
    for (double value : b)
        append_double(path, value);
    append_double(path, 0);
    append_double(path, 3);
    for (unsigned i = 0; i < 7; ++i) {
        append_u32(path, 1);
        append_u32(path, i >= 3 ? 1 : 0);
        append_double(path, a[i]);
        append_double(path, b[i]);
        append_double(path, 0);
        append_double(path, 0);
    }
    std::vector<unsigned char> packet{'D', 'L', 'Y', 'V', 'I', 'S', '0', '1'};
    append_u32(packet, 2);
    append_u32(packet, 1);
    append_u32(packet, 1);
    append_u32(packet, 1);
    append_u32(packet, 2);
    append_u32(packet, static_cast<std::uint32_t>(path.size()));
    append_u32(packet, 128);
    append_u32(packet, 8);
    packet.resize(dolly::kVisualizationHeaderBytes);
    append_double(packet, 0);
    append_double(packet, 3);
    packet.insert(packet.end(), path.begin(), path.end());
    return packet;
}
class SyntheticViewer {
    HANDLE mapping = nullptr;
    unsigned char* memory = nullptr;
    std::wstring name, viewer_name;
    std::uint32_t sequence = 0;

public:
    SyntheticViewer() {
        name = L"Local\\Dolly.Overlay.Smoke." + std::to_wstring(GetCurrentProcessId()) + L"." +
               std::to_wstring(GetTickCount64());
        viewer_name = name + L".viewer";
        dolly::visualization_worker_tick(name.c_str(), true);
        require(dolly::visualization_runtime_state() == dolly::VisualizationRuntimeState::Waiting &&
                    !dolly::visualization_snapshot(),
                "Missing optional viewer mapping must not publish guides");
        dolly::visualization_worker_tick(name.c_str(), false);
        mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0,
                                     static_cast<DWORD>(dolly::kVisualizationMappingBytes),
                                     viewer_name.c_str());
        require(mapping != nullptr, "Could not create synthetic viewer mapping");
        memory = static_cast<unsigned char*>(
            MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, dolly::kVisualizationMappingBytes));
        if (!memory) {
            CloseHandle(mapping);
            mapping = nullptr;
            throw std::runtime_error("Could not map synthetic viewer packet");
        }
        publish(viewer_packet());
        dolly::visualization_worker_tick(name.c_str(), true);
        const auto path = dolly::visualization_snapshot();
        require(dolly::visualization_runtime_state() == dolly::VisualizationRuntimeState::Ready &&
                    path && path->enabled() && path->camera_count() == 2,
                "Valid optional viewer mapping did not publish cameras");
    }
    ~SyntheticViewer() { close(); }
    void close() noexcept {
        dolly::visualization_worker_tick(name.c_str(), false);
        if (memory) {
            UnmapViewOfFile(memory);
            memory = nullptr;
        }
        if (mapping) {
            CloseHandle(mapping);
            mapping = nullptr;
        }
    }
    void publish(const std::vector<unsigned char>& packet) {
        require(packet.size() >= 12 && packet.size() <= dolly::kVisualizationMappingBytes,
                "Invalid synthetic viewer packet size");
        sequence += 2;
        InterlockedExchange(reinterpret_cast<volatile LONG*>(memory + 8),
                            static_cast<LONG>(sequence - 1));
        std::memcpy(memory, packet.data(), 8);
        std::memcpy(memory + 12, packet.data() + 12, packet.size() - 12);
        MemoryBarrier();
        InterlockedExchange(reinterpret_cast<volatile LONG*>(memory + 8),
                            static_cast<LONG>(sequence));
    }
    void tick() {
        Sleep(110);
        dolly::visualization_worker_tick(name.c_str(), true);
    }
    void check_lifecycle() {
        const auto before = dolly::visualization_snapshot();
        InterlockedExchange(reinterpret_cast<volatile LONG*>(memory + 8),
                            static_cast<LONG>(sequence + 1));
        tick();
        require(dolly::visualization_runtime_state() ==
                        dolly::VisualizationRuntimeState::Updating &&
                    dolly::visualization_snapshot() == before,
                "In-progress viewer write must retain the last complete snapshot");
        auto invalid = viewer_packet();
        invalid[0] = 'X';
        publish(invalid);
        tick();
        require(dolly::visualization_runtime_state() == dolly::VisualizationRuntimeState::Invalid &&
                    !dolly::visualization_snapshot(),
                "Invalid viewer packet left stale guides active");
        publish(viewer_packet());
        tick();
        require(dolly::visualization_runtime_state() == dolly::VisualizationRuntimeState::Ready &&
                    dolly::visualization_snapshot(),
                "Viewer did not recover after a valid replacement packet");
        close();
        require(dolly::visualization_runtime_state() ==
                        dolly::VisualizationRuntimeState::Disconnected &&
                    !dolly::visualization_snapshot(),
                "Disconnected editor left guides active");
        HANDLE remaining = OpenFileMappingW(FILE_MAP_READ, FALSE, viewer_name.c_str());
        if (remaining)
            CloseHandle(remaining);
        require(remaining == nullptr, "Viewer retained its mapping after disconnect");
    }
};

struct DrawRegions {
    std::size_t panel = 0, guides = 0;
};
DrawRegions render_regions(IDXGISwapChain* chain, ID3D11Device* device,
                           ID3D11DeviceContext* context, ID3D11RenderTargetView* target,
                           ID3D11Texture2D* backbuffer) {
    // Compare broad regions rather than exact antialiased pixels or UI text
    // positions. Clear each frame so hidden guides cannot pass with old pixels.
    const FLOAT clear[4] = {.04f, .08f, .95f, 1};
    context->ClearRenderTargetView(target, clear);
    context->OMSetRenderTargets(1, &target, nullptr);
    require(SUCCEEDED(chain->Present(0, 0)), "Viewer visibility Present failed");
    D3D11_TEXTURE2D_DESC desc{};
    backbuffer->GetDesc(&desc);
    desc.Usage = D3D11_USAGE_STAGING;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    desc.BindFlags = 0;
    desc.MiscFlags = 0;
    ID3D11Texture2D* staging = nullptr;
    require(SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &staging)),
            "Viewer readback texture creation failed");
    context->CopyResource(staging, backbuffer);
    D3D11_MAPPED_SUBRESOURCE pixels{};
    if (FAILED(context->Map(staging, 0, D3D11_MAP_READ, 0, &pixels))) {
        staging->Release();
        throw std::runtime_error("Viewer backbuffer readback failed");
    }
    DrawRegions result;
    ImGui::SetCurrentContext(screenshot_context);
    const float sx = desc.Width / ImGui::GetIO().DisplaySize.x;
    const float sy = desc.Height / ImGui::GetIO().DisplaySize.y;
    for (UINT y = 40; y < desc.Height - 140; ++y) {
        const auto* row = static_cast<const unsigned char*>(pixels.pData) + y * pixels.RowPitch;
        for (UINT x = 30; x < desc.Width - 10; ++x) {
            const auto* pixel = row + x * 4;
            const bool changed = pixel[0] < 7 || pixel[0] > 13 || pixel[1] < 17 || pixel[1] > 23 ||
                                 pixel[2] < 239 || pixel[2] > 245;
            bool over_ui = false;
            for (const auto* item : screenshot_context->Windows)
                if (item->Active && x/sx >= item->Pos.x - 20 && x/sx < item->Pos.x + item->Size.x + 20 &&
                    y/sy >= item->Pos.y - 20 && y/sy < item->Pos.y + item->Size.y + 20)
                    over_ui = true;
            if (changed) {
                if (x < 450)
                    ++result.panel;
                else if (x > 540 && !over_ui) {
                    ++result.guides;
                }
            }
        }
    }
    context->Unmap(staging, 0);
    staging->Release();
    return result;
}
void check_guide_visibility(IDXGISwapChain* chain, ID3D11Device* device,
                            ID3D11DeviceContext* context, ID3D11RenderTargetView* target,
                            ID3D11Texture2D* backbuffer) {
    const auto original = snapshot;
    snapshot.owner = dolly::EditorOwner::Flight;
    const auto flight = snapshot;
    auto draw = [&]() { return render_regions(chain, device, context, target, backbuffer); };
    const auto counters_before = dolly::overlay_diagnostics();
    auto pixels = draw();
    const auto counters_flight = dolly::overlay_diagnostics();
    require(counters_flight.draw_frames == counters_before.draw_frames + 1 &&
                counters_flight.guide_frames == counters_before.guide_frames + 1 &&
                counters_flight.panel_frames == counters_before.panel_frames,
            "Guide-only drawing must have its own counter without counting a panel frame");
    require(counters_flight.guide_lines > 0 && counters_flight.guide_labels > 0,
            "Guide diagnostics omitted the projected geometry");
    require(!counters_flight.overlay_active_since_ms && !counters_flight.present_active_since_ms,
            "Completed Present left an active rendering timer");
    require(counters_flight.overlay_max_us >= counters_flight.overlay_last_us &&
                counters_flight.present_max_us >= counters_flight.present_last_us,
            "Overlay and original-Present timings are inconsistent");
    require(pixels.guides > 30 && pixels.panel > 100,
            "Paused flight did not render visible camera guides without the panel");
    // Exercise the supported narrow layout here so the centered editor leaves
    // room for the synthetic world-space guide fixture on the right.
    snapshot.owner = dolly::EditorOwner::Panel;
    draw();
    ImGui::SetCurrentContext(screenshot_context);
    if (auto* panel = ImGui::FindWindowByName("Deadlock Dolly")) {
        screenshot_context->NavNextActivateId=panel->GetID("Layout");draw();draw();
        auto* layout=screenshot_context->OpenPopupStack.back().Window;
        screenshot_context->NavNextActivateId=layout->GetID("Arrange panels");draw();draw();
        ImGui::GetIO().AddKeyEvent(ImGuiKey_Escape,true);draw();
        ImGui::GetIO().AddKeyEvent(ImGuiKey_Escape,false);draw();
        ImGui::SetWindowSize(panel,ImVec2(520,panel->Size.y));
        ImGui::SetWindowPos(panel,ImVec2(20,20));
        draw();draw();
    }
    pixels = draw();
    require(pixels.panel > 100 && pixels.guides > 30,
            "Opening the panel hid the paused camera guides");
    snapshot.playing = true;
    const auto guides_before_playback = dolly::overlay_diagnostics().guide_frames;
    pixels = draw();
    require(dolly::overlay_diagnostics().guide_frames == guides_before_playback,
            "Playback without guides incorrectly counted a guide frame");
    if (!(pixels.panel > 100 && pixels.guides == 0))
        std::fprintf(stderr,"Playback pixel regions panel=%llu guides=%llu\n",pixels.panel,pixels.guides);
    require(pixels.panel > 100 && pixels.guides == 0,
            "Playback must hide guides while keeping the open panel visible");
    struct HiddenCase {
        const char* reason;
        unsigned field;
    };
    const HiddenCase cases[] = {
        {"Shot playback", 0},     {"Running replay", 1},         {"Game UI", 2},
        {"Console", 3},           {"Unfocused owner", 4},        {"Lost game focus", 5},
        {"Unready replay", 6},    {"Native flight inactive", 7}, {"Busy editor", 8},
        {"Unknown viewport", 9},  {"Disabled editor", 10},       {"Camera facing away", 11},
        {"Unknown view lens", 12}};
    for (const auto& test : cases) {
        snapshot = flight;
        switch (test.field) {
        case 0:
            snapshot.playing = true;
            break;
        case 1:
            snapshot.paused = false;
            break;
        case 2:
            snapshot.owner = dolly::EditorOwner::GameUI;
            break;
        case 3:
            snapshot.owner = dolly::EditorOwner::Console;
            break;
        case 4:
            snapshot.owner = dolly::EditorOwner::Unfocused;
            break;
        case 5:
            snapshot.focused = false;
            break;
        case 6:
            snapshot.ready = false;
            break;
        case 7:
            snapshot.manual_active = false;
            break;
        case 8:
            snapshot.busy = true;
            break;
        case 9:
            snapshot.view_width = 0;
            break;
        case 10:
            snapshot.enabled = false;
            break;
        case 11:
            snapshot.pose[4] = 180;
            break;
        case 12:
            snapshot.horizontal_fov = 0;
            break;
        }
        pixels = draw();
        const bool controls_visible = test.field != 2 && test.field != 3 && test.field != 4 &&
                                      test.field != 5 && test.field != 10;
        if (pixels.guides || (controls_visible ? pixels.panel < 100 : pixels.panel != 0)) {
            char message[128]{};
            std::snprintf(message, sizeof(message), "%s left editing graphics visible",
                          test.reason);
            throw std::runtime_error(message);
        }
    }
    snapshot = original;
    std::puts(
        "DX11 WARP viewer: paused flight/panel drawing and playback/UI/focus visibility gates passed.");
}

struct BufferLifetime {
    std::atomic<bool> retired{false};
};
// SetPrivateDataInterface holds one COM reference until the owning device
// child is destroyed. Observe that lifetime instead of relying on a driver's
// implementation-specific AddRef/Release return values.
// https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicechild-setprivatedatainterface
class BufferSentinel final : public IUnknown {
    std::atomic<ULONG> references{1};
    std::shared_ptr<BufferLifetime> lifetime;
    ~BufferSentinel() { lifetime->retired.store(true, std::memory_order_release); }

public:
    explicit BufferSentinel(std::shared_ptr<BufferLifetime> value) : lifetime(std::move(value)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** result) override {
        if (!result)
            return E_POINTER;
        *result = nullptr;
        if (!IsEqualIID(iid, __uuidof(IUnknown)))
            return E_NOINTERFACE;
        *result = static_cast<IUnknown*>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override {
        return references.fetch_add(1, std::memory_order_relaxed) + 1;
    }
    ULONG STDMETHODCALLTYPE Release() override {
        const auto remaining = references.fetch_sub(1, std::memory_order_acq_rel) - 1;
        if (!remaining)
            delete this;
        return remaining;
    }
};

std::shared_ptr<BufferLifetime> watch_buffer(ID3D11Buffer* buffer) {
    static const GUID sentinel_id = {
        0x1622bc48, 0x49b1, 0x466a, {0x95, 0xb3, 0xa4, 0x3b, 0xe0, 0x34, 0x11, 0x8f}};
    auto lifetime = std::make_shared<BufferLifetime>();
    auto* sentinel = new BufferSentinel(lifetime);
    const auto result = buffer->SetPrivateDataInterface(sentinel_id, sentinel);
    sentinel->Release();
    require(SUCCEEDED(result), "Could not attach buffer lifetime sentinel");
    require(!lifetime->retired.load(std::memory_order_acquire),
            "Buffer did not retain its lifetime sentinel");
    return lifetime;
}

void retire_game_buffers(ID3D11DeviceContext* context, ID3D11Query* completed,
                         const std::vector<std::shared_ptr<BufferLifetime>>& lifetimes) {
    // D3D11 may defer destruction. Release game bindings, submit pending work,
    // and wait for it before checking lifetime flags; a live overlay must not
    // retain earlier game vertex/index buffers in its private context state.
    // https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicecontext-flush
    context->ClearState();
    context->End(completed);
    context->Flush();
    const auto deadline = GetTickCount64() + 3000;
    for (;;) {
        BOOL ready = FALSE;
        const auto result =
            context->GetData(completed, &ready, sizeof(ready), D3D11_ASYNC_GETDATA_DONOTFLUSH);
        require(SUCCEEDED(result), "GPU completion query failed during buffer-retirement check");
        if (result == S_OK && ready)
            break;
        require(GetTickCount64() < deadline,
                "GPU completion timed out during buffer-retirement check");
        Sleep(1);
    }
    context->Flush();
    for (std::size_t i = 0; i < lifetimes.size(); ++i) {
        if (!lifetimes[i]->retired.load(std::memory_order_acquire)) {
            char message[128]{};
            std::snprintf(message, sizeof(message),
                          "Overlay retained retired game %s buffer at frame %zu",
                          i % 2 ? "index" : "vertex", i / 2);
            throw std::runtime_error(message);
        }
    }
}

void stress_game_buffer_lifetimes(IDXGISwapChain* chain, ID3D11Device* device,
                                  ID3D11DeviceContext* context, ID3D11RenderTargetView* target) {
    constexpr int frames = 384;
    constexpr dolly::EditorOwner owners[] = {dolly::EditorOwner::Panel, dolly::EditorOwner::Flight,
                                             dolly::EditorOwner::GameUI};
    std::vector<std::shared_ptr<BufferLifetime>> lifetimes;
    lifetimes.reserve(frames * 2);
    D3D11_QUERY_DESC query_desc{D3D11_QUERY_EVENT, 0};
    ID3D11Query* completed = nullptr;
    require(SUCCEEDED(device->CreateQuery(&query_desc, &completed)),
            "Could not create buffer-retirement query");
    try {
        for (int frame = 0; frame < frames; ++frame) {
            MSG message{};
            while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            snapshot.owner = owners[(frame / 4) % 3];
            require(dolly::visualization_snapshot() != nullptr,
                    "Buffer lifetime stress lost its camera guides");
            D3D11_BUFFER_DESC buffer_desc{};
            buffer_desc.ByteWidth = 1024;
            buffer_desc.Usage = D3D11_USAGE_DEFAULT;
            buffer_desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
            ID3D11Buffer* vertex = nullptr;
            ID3D11Buffer* index = nullptr;
            require(SUCCEEDED(device->CreateBuffer(&buffer_desc, nullptr, &vertex)),
                    "Synthetic game vertex-buffer creation failed");
            buffer_desc.BindFlags = D3D11_BIND_INDEX_BUFFER;
            const auto index_result = device->CreateBuffer(&buffer_desc, nullptr, &index);
            if (FAILED(index_result)) {
                vertex->Release();
                throw std::runtime_error("Synthetic game index-buffer creation failed");
            }
            lifetimes.push_back(watch_buffer(vertex));
            lifetimes.push_back(watch_buffer(index));
            const UINT stride = 16u * (1u + static_cast<UINT>(frame % 2));
            const UINT vertex_offset = 16u * static_cast<UINT>(frame % 4);
            const UINT index_offset = 4u * static_cast<UINT>(frame % 8);
            const auto index_format = frame % 2 ? DXGI_FORMAT_R32_UINT : DXGI_FORMAT_R16_UINT;
            context->IASetVertexBuffers(0, 1, &vertex, &stride, &vertex_offset);
            context->IASetIndexBuffer(index, index_format, index_offset);
            context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            context->OMSetRenderTargets(1, &target, nullptr);
            const auto presented = chain->Present(0, 0);
            ID3D11Buffer* after_vertex = nullptr;
            ID3D11Buffer* after_index = nullptr;
            UINT after_stride = 0, after_vertex_offset = 0, after_index_offset = 0;
            DXGI_FORMAT after_index_format{};
            context->IAGetVertexBuffers(0, 1, &after_vertex, &after_stride, &after_vertex_offset);
            context->IAGetIndexBuffer(&after_index, &after_index_format, &after_index_offset);
            const bool restored = after_vertex == vertex && after_index == index &&
                                  after_stride == stride && after_vertex_offset == vertex_offset &&
                                  after_index_format == index_format &&
                                  after_index_offset == index_offset;
            if (after_vertex)
                after_vertex->Release();
            if (after_index)
                after_index->Release();
            vertex->Release();
            index->Release();
            require(SUCCEEDED(presented), "Present failed during game-buffer lifetime stress");
            require(restored, "Overlay did not restore the game's vertex/index-buffer bindings");
            if ((frame + 1) % 32 == 0)
                retire_game_buffers(context, completed, lifetimes);
        }
    } catch (...) {
        completed->Release();
        throw;
    }
    completed->Release();
    snapshot.owner = dolly::EditorOwner::Panel;
    std::puts(
        "DX11 WARP lifetime stress: 384 panel/guide/game-UI frames, 768 game buffers retired.");
}
}
static bool framebuffer_scale_probe = false;
namespace dolly {
bool framing_grid_enabled_stub = false;
EditorCinematicStatus cinematic_status_stub{};
bool editor_cinematic_status(EditorCinematicStatus& out) noexcept {
    out = cinematic_status_stub;
    return out.token != 0;
}
EditorSnapshot editor_snapshot() noexcept {
    return snapshot;
}
bool editor_framing_grid_enabled() noexcept {
    return framing_grid_enabled_stub;
}
bool editor_request_framing_factor(double factor) noexcept { return std::isfinite(factor) && factor > 0; }
bool replay_third_player_stub = false;
unsigned replay_events_status_stub = 2;
bool editor_replay_events(EditorReplayEvents& out) noexcept {
    out={}; std::memcpy(out.magic,"DLYKILL1",8);out.abi=1;out.status=replay_events_status_stub;out.total_ticks=146926;
    out.player_count=2;out.players[0].id=1;out.players[1].id=2;
    std::strcpy(out.players[0].name,"Ivy player");std::strcpy(out.players[1].name,"Haze player");
    if(replay_third_player_stub) {
        out.player_count=3;out.players[2].id=3;
        std::strcpy(out.players[2].name,"Unrelated player");
    }
    out.count=4;out.kills[0]={4000,1,2};out.kills[1]={5000,2,1};out.kills[2]={6000,1,2};out.kills[3]={8000,2,1};
    std::strcpy(out.message,"4 kills in this replay");return true;
}
bool editor_lite_replay_info(EditorLiteReplayInfo& out) noexcept {
    out = {};std::memcpy(out.magic,"DLYLITE1",8);out.abi=1;out.revision=camera_revision_stub;
    out.first=camera_first_stub;out.count=std::min(snapshot.camera_count-camera_first_stub,32u);out.flags=(replay_info_known_stub ? 3 : 1) | (shader_loading_stub ? 4 : 0);out.start_tick=3389;out.total_ticks=replay_info_known_stub ? 146926 : -1;out.tick_rate=64;
    for(unsigned i=0;i<out.count;i++)out.ticks[i]=3389+192*(out.first+i);
    return true;
}
bool editor_camera_list(EditorCameraList& out) noexcept {
    out = {};
    std::memcpy(out.magic, "DLYCAMS1", 8);
    out.abi = 1;
    out.revision = camera_revision_stub;
    out.total = snapshot.camera_count;
    out.first = camera_first_stub;
    out.count = std::min<std::uint32_t>(out.total-out.first, kEditorCameraListCount);
    out.flags = 3;
    for (std::uint32_t i = 0; i < out.count; ++i)
        out.rows[i] = {double(out.first+i) * 3 + camera_time_bias_stub, 16.0 / 9, double(out.first+i) * 4, i % 2, 0};
    return true;
}
EditorBinding editor_binding_snapshot(EditorAction action) noexcept {
    EditorBinding binding{};
    // A representative default so the key-cap hints render in the smoke test.
    if (action == EditorAction::Capture) {
        binding.vk = 'K';
        binding.modifiers = 3;
    } else if (action == EditorAction::PlayPath) {
        binding.vk = 0x74; // F5
    } else if (action == EditorAction::PlayPause) {
        binding.vk = 'P';
    } else if (action == EditorAction::Stop) {
        binding.vk = 0x08; // Backspace
    } else if (action == EditorAction::Flight) {
        binding.vk = 0x79; // F10
    } else if (action == EditorAction::GameUI) {
        binding.vk = 0x78; // F9
    }
    return binding;
}
bool editor_roster_snapshot(EditorRoster& out) noexcept {
    out = EditorRoster{};
    if (!snapshot.attach_available)
        return false;
    out.count = 1;
    std::snprintf(out.players[0].model_path, sizeof(out.players[0].model_path),
                  "models/heroes_staging/astro/astro.vmdl");
    out.players[0].handle = 19464268;
    out.players[0].entity_index = 76;
    return true;
}
bool editor_enqueue(EditorAction action, double value, const CameraPose* pose) noexcept {
    try {
        observed_actions.push_back({action, value, pose ? (*pose)[0] : 0,
                                    pose ? (*pose)[1] : 0, pose ? *pose : CameraPose{}});
    } catch (...) {
        return false;
    }
    return true;
}
bool editor_bones_snapshot(EditorBones& out) noexcept {
    out = EditorBones{};
    out.count = out.total = 3;
    std::snprintf(out.names[0], 64, "head");
    std::snprintf(out.names[1], 64, "hand_R");
    std::snprintf(out.names[2], 64, "weapon_bone_R");
    return snapshot.attach_available;
}
bool editor_panel_visible() noexcept {
    return snapshot.owner == EditorOwner::Panel;
}
void editor_set_owner(EditorOwner value) noexcept {
    snapshot.owner = value;
}
void editor_overlay_available(bool value) noexcept {
    available = value;
}
void editor_text_input_active(bool) noexcept {
    if (ImGui::GetCurrentContext()) {
        screenshot_context = ImGui::GetCurrentContext();
        const auto& io = ImGui::GetIO();
        for (int i = 0; i < 5; ++i)
            observed_mouse_down[i] = io.MouseDown[i];
        present_keeps_os_cursor = (io.ConfigFlags & ImGuiConfigFlags_NoMouseCursorChange) != 0;
        if (framebuffer_scale_probe && ImGui::GetCurrentContext()->WithinFrameScope) {
            // Use client-coordinate geometry and a tight clip near the bottom
            // right. A smaller swapchain must scale BOTH viewport and scissors.
            auto* draw = ImGui::GetForegroundDrawList();
            const ImVec2 low(io.DisplaySize.x * .88f, io.DisplaySize.y * .88f);
            const ImVec2 high(io.DisplaySize.x * .98f, io.DisplaySize.y * .98f);
            draw->PushClipRect(low, ImVec2(io.DisplaySize.x * .93f, high.y));
            draw->AddRectFilled(low, high, IM_COL32(255, 0, 255, 255));
            draw->PopClipRect();
        }
    }
}
void editor_attach_window(HWND value) noexcept {
    attached = value;
}
bool editor_window_message(HWND, UINT, WPARAM, LPARAM, LRESULT&) noexcept {
    return false;
}
}
// Exercise presentation state directly as well as through DX11. This keeps
// delayed acknowledgement checks deterministic and uses real ImGui controls.
static void panel_option_regressions() {
    auto* previous_context = ImGui::GetCurrentContext();
    const auto previous_snapshot = snapshot;
    auto* test_context = ImGui::CreateContext();
    ImGui::SetCurrentContext(test_context);
    auto& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(1920, 1080);
    io.DeltaTime = 1.f / 60;
    io.IniFilename = nullptr;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    dolly::OverlayPanel panel;
    panel.style_panel();
    panel.load_panel_fonts(1);
    io.Fonts->Build();
    snapshot.dof_available = true;
    snapshot.dof = {1, 1, -100, 0, 180, 2000, -100, 0, 180, 2000, .5};
    snapshot.video_fixed_step = false;
    snapshot.video_depth = false;
    auto frame = [&] {
        ImGui::NewFrame();
        panel.draw_panel(snapshot);
        panel.draw_lite_campaths(snapshot);
        panel.draw_lite_timeline(snapshot);
        ImGui::Render();
    };
    auto card = [&](const char* name) -> ImGuiWindow* {
        for (auto* window : test_context->Windows)
            if (std::strstr(window->Name, name)) return window;
        for (auto* window : test_context->Windows)
            std::fprintf(stderr, "Test window: %s (active %d, skip %d, size %.0f %.0f)\n", window->Name, window->Active, window->SkipItems, window->Size.x, window->Size.y);
        throw std::runtime_error(std::string("Presentation test card missing: ") + name);
    };
    frame(); frame(); frame();
    auto* main = ImGui::FindWindowByName("Deadlock Dolly");
    test_context->NavNextActivateId=main->GetID("Layout");frame();frame();
    auto* layout=test_context->OpenPopupStack.back().Window;
    test_context->NavNextActivateId=layout->GetID("Arrange panels");frame();frame();
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    ImGui::SetWindowSize(main, ImVec2(900, 820));
    ImGui::SetWindowPos(main, ImVec2(420, 20));
    ImGui::FocusWindow(main);
    frame(); frame();
    auto* shared_transport = ImGui::FindWindowByName("##lite-timeline");
    auto* reworked_campaths = ImGui::FindWindowByName("##lite-campaths");
    require(reworked_campaths && reworked_campaths->Size.x >= 250,
            "Campaths needs a readable card width, including the empty state");
    require(shared_transport && main->Pos.y + main->Size.y <= shared_transport->Pos.y,
            "Resizing the main editor covers the shared timeline");
    // Custom kill hit targets must obey disabled replay state too. Ordinary
    // ImGui widgets already honor BeginDisabled; hand-drawn markers need it.
    observed_actions.clear();
    const float kill_x = panel.timeline_x0() + (panel.timeline_x1() - panel.timeline_x0()) * 4000.f / 146925.f;
    io.AddMousePosEvent(kill_x, panel.timeline_y() - 10);
    snapshot.busy = true;
    frame(); frame();
    io.AddMouseButtonEvent(0, true);
    frame(); frame();
    require(observed_actions.empty(), "Busy replay accepts a custom kill-marker seek");
    io.AddMouseButtonEvent(0, false);
    snapshot.busy = false;
    frame(); frame();
    io.AddMouseButtonEvent(0, true);
    frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::SeekReplayTick &&
                observed_actions[0].value == 4000,
            "Ready replay kill marker no longer seeks its actual tick");
    io.AddMouseButtonEvent(0, false);
    frame(); frame();
    observed_actions.clear();
    // A row can be reordered by a different edit during live bank preview.
    // Never continue the gesture on the new occupant of the same row index.
    auto* campaths = ImGui::FindWindowByName("##lite-campaths");
    auto* camera_table=test_context->Tables.GetByKey(campaths->GetID("##lite-campath-details"));
    require(camera_table && camera_table->ColumnsCount==4,"Campaths must use the reference table");
    const float bank_x=(camera_table->Columns[3].WorkMinX+camera_table->Columns[3].WorkMaxX)*.5f;
    const float bank_y=camera_table->OuterRect.Min.y+camera_table->InstanceDataFirst.LastTopHeadersRowHeight+camera_table->RowMinHeight*.5f;
    io.MouseClickedTime[0] = -1e30;
    io.AddMousePosEvent(bank_x, bank_y);
    io.AddMouseButtonEvent(0, true);
    frame(); frame();
    io.AddMousePosEvent(bank_x + 16, bank_y);
    frame(); frame();
    require(!observed_actions.empty() && observed_actions.back().action == dolly::EditorAction::SetCameraRoll,
            "Bank drag did not retain live preview");
    observed_actions.clear();
    camera_revision_stub = 8;
    camera_time_bias_stub = 1;
    frame(); frame();
    io.AddMousePosEvent(bank_x + 32, bank_y);
    frame(); frame();
    io.AddMouseButtonEvent(0, false);
    frame(); frame();
    require(observed_actions.empty(), "Bank drag continued on a reordered camera row");
    camera_revision_stub = 7;
    camera_time_bias_stub = 0;
    frame(); frame();
    // Confirmation belongs to the reviewed path, not an incoming replacement.
    observed_actions.clear();
    test_context->NavNextActivateId = campaths->GetID("Clear All");
    frame(); frame();
    auto* confirmation = ImGui::FindWindowByName("Clear cameras?");
    require(confirmation && confirmation->Active, "Clear All confirmation missing");
    io.AddMousePosEvent(kill_x, panel.timeline_y() - 10);
    frame(); frame();
    io.AddMouseButtonEvent(0, true);
    frame(); frame();
    require(observed_actions.empty(), "Kill marker seeks through a modal confirmation");
    io.AddMouseButtonEvent(0, false);
    frame(); frame();
    camera_revision_stub = 8;
    frame(); frame();
    test_context->NavNextActivateId = confirmation->GetID("Clear");
    frame(); frame();
    require(observed_actions.empty(), "Changed campath can be cleared through an old confirmation");
    camera_revision_stub = 7;
    snapshot.busy = true;
    frame(); frame();
    test_context->NavNextActivateId = confirmation->GetID("Clear");
    frame(); frame();
    require(observed_actions.empty(), "Busy campath can be cleared through an open confirmation");
    snapshot.busy = false;
    test_context->NavNextActivateId = confirmation->GetID("Cancel");
    frame(); frame();
    test_context->NavNextActivateId = campaths->GetID("Clear All");
    frame(); frame();
    test_context->NavNextActivateId = confirmation->GetID("Clear");
    frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::ClearCameraPath &&
                observed_actions[0].revision == 7,
            "Reviewed campath cannot be cleared with its original revision");
    observed_actions.clear();
    test_context->NavNextActivateId = main->GetID("Look###LOOK");
    frame(); frame();
    auto* dof = card("##dof-card");
    test_context->NavNextActivateId = dof->GetID("Individual focus overrides");
    frame(); frame();
    const auto* individual = test_context->Tables.GetByKey(dof->GetID("##individual-focus"));
    require(individual && individual->ColumnsCount == 2,
            "Look page omits the four individual native focus overrides");
    for (int index : {6, 7, 8, 9}) {
        observed_actions.clear();
        const auto field_seed = ImHashData(&index, sizeof(index), individual->ID);
        test_context->NavNextActivateId = ImGui::GetIDWithSeed("##value", nullptr, field_seed);
        test_context->NavNextActivateFlags = ImGuiActivateFlags_PreferInput;
        frame(); frame();
        require(test_context->InputTextState.ID == test_context->ActiveId && test_context->ActiveId,
                "Individual focus override cannot accept an exact typed value");
        io.AddInputCharactersUTF8("12.50");
        frame();
        io.AddKeyEvent(ImGuiKey_Enter, true);
        frame();
        io.AddKeyEvent(ImGuiKey_Enter, false);
        frame(); frame();
        require(observed_actions.size() == 1 &&
                    unsigned(observed_actions[0].action) == unsigned(dolly::EditorAction::SetDofEnabled) + index &&
                    std::abs(observed_actions[0].value - 12.5) < .001,
                "Individual focus override dispatches the wrong effect or value");
    }
    test_context->NavNextActivateId = main->GetID("Export###EXPORT");
    frame(); frame();
    auto* settings = card("##export-settings");
    observed_actions.clear();
    test_context->NavNextActivateId = settings->GetID("Fixed-step export");
    frame(); frame();
    require(!observed_actions.empty() && observed_actions.back().action == dolly::EditorAction::SetVideoFixedStep,
            "Fixed-step export checkbox is disconnected");
    // Capture and layers are available together in the continuous Export tab.
    frame(); frame();
    auto* passes = card("##export-passes");
    test_context->NavNextActivateId = passes->GetID("Depth master (.mov)");
    frame(); frame();
    frame(); frame();
    const auto checkmark = ImGui::GetColorU32(ImGuiCol_CheckMark);
    bool fixed_step_checked = false;
    for (const auto& vertex : settings->DrawList->VtxBuffer)
        fixed_step_checked |= (vertex.col & 0x00ffffffu) == (checkmark & 0x00ffffffu);
    require(fixed_step_checked,
            "A second export edit erases the first pending checkbox before acknowledgement");
    // Each remaining tab has its own finished working surface. Follow and
    // Bone targets remain separate from the numeric framing controls.
    test_context->NavNextActivateId = main->GetID("Follow###FOLLOW");
    snapshot.follow_available = true;
    snapshot.follow_pending = true;
    snapshot.attach_available = true; // The shared synthetic roster producer is available.
    frame(); frame();
    auto* follow_target = card("##follow-card");
    auto* follow_framing = card("##follow-framing");
    require(follow_target->Active && follow_framing->Active,
            "Follow target and framing surfaces are not both available");
    test_context->NavNextActivateId = follow_target->GetID("##follow-hero");
    frame(); frame();
    require(!test_context->OpenPopupStack.empty(), "Follow hero chooser cannot open");
    auto* hero_popup = test_context->OpenPopupStack.back().Window;
    int hero_index = 0;
    const auto hero_seed = ImHashData(&hero_index, sizeof(hero_index), hero_popup->IDStack.back());
    test_context->NavNextActivateId = ImGui::GetIDWithSeed("Holliday (76)", nullptr, hero_seed);
    frame(); frame();
    observed_actions.clear();
    test_context->NavNextActivateId = follow_framing->GetID("Preview Follow");
    frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::StartGameFollow &&
                observed_actions[0].value == snapshot.follow_distance &&
                observed_actions[0].pose[0] == snapshot.follow_shoulder &&
                observed_actions[0].pose[1] == snapshot.follow_height &&
                observed_actions[0].pose[2] == 0 && observed_actions[0].pose[3] == 19464268 &&
                observed_actions[0].pose[4] == 76,
            "Follow framing changes the existing target/offset payload");
    observed_actions.clear();
    test_context->NavNextActivateId = follow_target->GetID("Restore rig");
    frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::StopGameFollow,
            "Follow layout changes its existing restore action");
    test_context->NavNextActivateId = main->GetID("Bone Picker###BONE PICKER");
    snapshot.attach_available = true;
    snapshot.attach_selected = true;
    frame(); frame();
    auto* attach_target = card("##attach-card");
    auto* attach_framing = card("##attach-framing");
    require(attach_target->Active && attach_framing->Active,
            "Bone target and framing surfaces are not both available");
    observed_actions.clear();
    test_context->NavNextActivateId = attach_target->GetID("Snap");
    frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::AttachSnap,
            "Bone layout changes its existing Snap action");
    observed_actions.clear();
    test_context->NavNextActivateId = attach_framing->GetID("##attach-offset-0");
    test_context->NavNextActivateFlags = ImGuiActivateFlags_PreferInput;
    frame(); frame();
    require(test_context->InputTextState.ID == test_context->ActiveId && test_context->ActiveId,
            "Bone framing cannot type an exact offset");
    io.AddInputCharactersUTF8("5.50");
    frame();
    io.AddKeyEvent(ImGuiKey_Enter, true); frame();
    io.AddKeyEvent(ImGuiKey_Enter, false); frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::SetAttachOffsets &&
                observed_actions[0].value == 0 && observed_actions[0].pose[0] == 5.5 &&
                observed_actions[0].pose[2] == snapshot.attach_offsets[2],
            "Bone framing changes its existing six-axis offset payload");
    test_context->NavNextActivateId = main->GetID("Export###EXPORT");
    frame(); frame();
    observed_actions.clear();
    test_context->NavNextActivateId = main->GetID("Record video");
    frame(); frame();
    require(observed_actions.size() == 1 && observed_actions[0].action == dolly::EditorAction::StartVideo &&
                observed_actions[0].value == 0,
            "Export recording action is not retained in its fixed footer");
    ImGui::DestroyContext(test_context);
    ImGui::SetCurrentContext(previous_context);
    snapshot = previous_snapshot;
    observed_actions.clear();
    std::puts("Look focus overrides and concurrent pending export controls passed.");
}
static void ui_rework_regressions() {
    auto* previous = ImGui::GetCurrentContext();
    const auto original = snapshot;
    auto* ctx=ImGui::CreateContext();
    ImGui::SetCurrentContext(ctx);
    auto& io=ImGui::GetIO();
    io.DisplaySize=ImVec2(1920,1080); io.DeltaTime=1.f/60;
    io.IniFilename=nullptr; io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard;
    dolly::OverlayPanel panel; panel.style_panel(); panel.initialize_layout(); panel.load_panel_fonts(1);
    io.Fonts->Build();
    snapshot.camera_count=2; snapshot.tick=4000; snapshot.paused=true;
    snapshot.ready=true; snapshot.busy=false; snapshot.playing=false;
    snapshot.attach_preview=false; snapshot.follow_available=true;
    snapshot.attach_available=true; snapshot.dof_available=true;
    auto frame=[&] { ImGui::NewFrame(); panel.draw_panel(snapshot); panel.draw_lite_campaths(snapshot);
                    panel.draw_lite_timeline(snapshot); ImGui::Render(); };
    auto settle=[&] { for(int i=0;i<30;++i) frame(); };
    settle();
    auto* main=ImGui::FindWindowByName("Deadlock Dolly");
    auto* timeline=ImGui::FindWindowByName("##lite-timeline");
    auto* paths=ImGui::FindWindowByName("##lite-campaths");
    require(ctx->Tables.GetByKey(paths->GetID("##lite-campath-details")) != nullptr,
            "Campaths must use the four-column reference table");
    const auto menu_before=main->Pos,paths_before=paths->Pos,timeline_before=timeline->Pos;
    io.AddMousePosEvent(main->Pos.x+main->Size.x*.5f,main->Pos.y+7);frame();
    io.AddMouseButtonEvent(ImGuiMouseButton_Left,true);frame();
    io.AddMousePosEvent(io.MousePos.x+48,io.MousePos.y+30);frame();frame();
    io.AddMouseButtonEvent(ImGuiMouseButton_Left,false);settle();
    require(main->Pos.x>menu_before.x+40 && main->Pos.y>menu_before.y+20,
            "Main menu cannot move without Arrange panels");
    require(paths->Pos.x==paths_before.x && paths->Pos.y==paths_before.y &&
            timeline->Pos.x==timeline_before.x && timeline->Pos.y==timeline_before.y,
            "Moving only the main menu moves another panel");
    auto activate=[&](ImGuiWindow* window,const char* item) {
        if(!window) {std::fprintf(stderr,"Missing activation window for %s\n",item);require(false,"Missing activation window");}
        ctx->NavNextActivateId=window->GetID(item);frame();frame();
    };
    auto find_card=[&](const char* name) -> ImGuiWindow* {
        for(auto* window:ctx->Windows)if(window->Active && std::strstr(window->Name,name))return window;
        return nullptr;
    };
    auto drag_section=[&](ImGuiWindow* source,ImGuiWindow* target) {
        require(source && target,"Section drag fixture is missing a card");
        const ImVec2 from(source->Pos.x+source->Size.x-9,source->Pos.y+source->WindowPadding.y+7);
        const ImVec2 to(target->Pos.x+target->WindowPadding.x+18,target->Pos.y+target->WindowPadding.y+7);
        io.AddMousePosEvent(from.x,from.y);frame();frame();
        io.AddMouseButtonEvent(ImGuiMouseButton_Left,true);frame();
        io.AddMousePosEvent(from.x+20,from.y);frame();frame();
        require(ctx->DragDropActive,"Section header does not begin a real drag");
        io.AddMousePosEvent(to.x,to.y);frame();frame();
        io.AddMouseButtonEvent(ImGuiMouseButton_Left,false);frame();settle();
    };
    char temporary_directory[MAX_PATH]{},section_file[MAX_PATH]{};
    require(GetTempPathA(MAX_PATH,temporary_directory) && GetTempFileNameA(temporary_directory,"dol",0,section_file),"Cannot create isolated layout preference test");
    io.IniFilename=section_file;
    observed_actions.clear();
    auto* replay_card=find_card("##cameras-card");auto* free_card=find_card("##flight-card");
    // Locked sections must keep controls and arrangement untouched.
    io.AddMousePosEvent(free_card->Pos.x+25,free_card->Pos.y+15);frame();frame();
    io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(io.MousePos.x+25,io.MousePos.y+25);frame();frame();
    require(!ctx->DragDropActive,"Sections can still be dragged with Arrange panels off");
    io.AddMouseButtonEvent(0,false);settle();
    activate(main,"Layout");auto* arrange_popup=ctx->OpenPopupStack.back().Window;
    activate(arrange_popup,"Arrange panels");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    drag_section(free_card,replay_card);
    std::ifstream section_disk(section_file,std::ios::binary);
    const std::string disk_ini((std::istreambuf_iterator<char>(section_disk)),std::istreambuf_iterator<char>());
    require(disk_ini.find("Sections0=1,0,2,3")!=std::string::npos,"Section drop is not saved automatically to disk");
    section_disk.close();io.IniFilename=nullptr;require(DeleteFileA(section_file),"Cannot remove isolated layout preference test");
    require(free_card->Pos.x<replay_card->Pos.x,"Free camera and Replay/shot do not swap places");
    require(observed_actions.empty(),"Rearranging sections emits a backend action");
    ctx->NavNextActivateId=replay_card->GetID("Capture camera here");frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::Capture,
            "Reordered Replay/shot controls lost their existing action");
    observed_actions.clear();
    std::size_t section_ini_length=0;
    const std::string section_ini(ImGui::SaveIniSettingsToMemory(&section_ini_length));
    require(section_ini.find("EditorCustom=1")!=std::string::npos && section_ini.find("\nCustom=1\n")!=std::string::npos &&
            section_ini.find("Sections0=1,0,2,3")!=std::string::npos,
            "Independent menu position and section order are not serialized");
    auto* restored_context=ImGui::CreateContext();ImGui::SetCurrentContext(restored_context);
    auto& restored_io=ImGui::GetIO();restored_io.DisplaySize=io.DisplaySize;restored_io.DeltaTime=1.f/60;
    dolly::OverlayPanel restored;restored.style_panel();restored.initialize_layout();restored.load_panel_fonts(1);restored_io.Fonts->Build();
    ImGui::LoadIniSettingsFromMemory(disk_ini.data(),disk_ini.size());
    auto restored_frame=[&] {ImGui::NewFrame();restored.draw_panel(snapshot);restored.draw_lite_campaths(snapshot);restored.draw_lite_timeline(snapshot);ImGui::Render();};
    for(int i=0;i<30;++i)restored_frame();
    ImGuiWindow* restored_replay=nullptr,*restored_free=nullptr;
    for(auto* window:restored_context->Windows)if(window->Active) {
        if(std::strstr(window->Name,"##cameras-card"))restored_replay=window;
        if(std::strstr(window->Name,"##flight-card"))restored_free=window;
    }
    require(restored_replay && restored_free && restored_free->Pos.x<restored_replay->Pos.x,
            "Section order does not survive a fresh UI instance");
    auto* restored_main=ImGui::FindWindowByName("Deadlock Dolly");
    require(std::abs(restored_main->Pos.x-main->Pos.x)<1 && std::abs(restored_main->Pos.y-main->Pos.y)<1,
            "Independent main-menu position does not restore");
    const char* malformed="[DollyUI][Preferences]\nSections0=99,0,2,3\nSections0=0,0,2,3\nSections3=1,1,2,3\nSections-1=0,1,2,3\nSections0=0,1,2,3junk\n";
    ImGui::LoadIniSettingsFromMemory(malformed);for(int i=0;i<3;++i)restored_frame();
    require(restored_free->Pos.x<restored_replay->Pos.x,"Malformed layout data overwrites a valid section order");
    ImGui::DestroyContext(restored_context);ImGui::SetCurrentContext(ctx);
    std::puts("Independent header drag, real section swap, preserved actions, fresh-instance restore and invalid-layout rejection passed.");
    activate(main,"Bone Picker###BONE PICKER");settle();
    auto* bone_size_card=find_card("##attach-card");
    activate(bone_size_card,"Reset");settle();
    const auto bone_row_before=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main];observed_actions.clear();
    const auto bone_size_before=bone_size_card->Size;const auto bone_font_before=bone_size_card->FontRefSize;
    const ImVec2 resize_point(bone_size_card->Pos.x+bone_size_card->Size.x-7,bone_size_card->Pos.y+bone_size_card->Size.y-7);
    io.AddMousePosEvent(resize_point.x,resize_point.y);frame();frame();
    io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(resize_point.x+55,resize_point.y+55);frame();frame();
    io.AddMouseButtonEvent(0,false);settle();
    if(!(bone_size_card->Size.x>bone_size_before.x+20 && bone_size_card->Size.y>bone_size_before.y+30))
        std::fprintf(stderr,"Resize bone %.1fx%.1f -> %.1fx%.1f active %u hovered %s\n",bone_size_before.x,bone_size_before.y,bone_size_card->Size.x,bone_size_card->Size.y,ctx->ActiveId,ctx->HoveredWindow ? ctx->HoveredWindow->Name : "none");
    require(bone_size_card->Size.x>bone_size_before.x+20 && bone_size_card->Size.y>bone_size_before.y+30,"Bone camera resize handle does not enlarge its section");
    require(bone_size_card->FontRefSize==bone_font_before,"Section resize changes the font size");
    activate(bone_size_card,"Reset");settle();
    const auto bone_row_after=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main];observed_actions.clear();
    require(bone_row_after.Min.y>bone_row_before.Min.y+5 && bone_row_after.GetHeight()>bone_row_before.GetHeight()+1,
            "Taller sections do not distribute their controls vertically");
    const std::string resized_ini(ImGui::SaveIniSettingsToMemory());
    require(resized_ini.find("Heights2=0.00,0.00,0.00,0.00")==std::string::npos,"Section height is not persisted");
    if(const auto* output=std::getenv("DOLLY_UI_TEST_RESIZED_LAYOUT_OUT")) {
        std::ofstream saved(output,std::ios::binary);saved<<resized_ini;require(saved.good(),"Cannot save resized-layout capture fixture");
    }
    const auto resized_expected=bone_size_card->Size;
    auto* size_context=ImGui::CreateContext();ImGui::SetCurrentContext(size_context);
    auto& size_io=ImGui::GetIO();size_io.DisplaySize=io.DisplaySize;size_io.DeltaTime=1.f/60;
    dolly::OverlayPanel size_panel;size_panel.style_panel();size_panel.initialize_layout();size_panel.load_panel_fonts(1);size_io.Fonts->Build();
    ImGui::LoadIniSettingsFromMemory(resized_ini.data(),resized_ini.size());
    ImGui::LoadIniSettingsFromMemory("[Window][##lite-campaths]\nPos=16,588\nSize=340,280\n\n[DollyUI][Preferences]\nSidebarWidthCurrent=0\n");
    auto size_frame=[&]{ImGui::NewFrame();size_panel.draw_panel(snapshot);size_panel.draw_lite_campaths(snapshot);size_panel.draw_lite_timeline(snapshot);ImGui::Render();};
    size_frame();size_context->NavNextActivateId=ImGui::FindWindowByName("Deadlock Dolly")->GetID("Bone Picker###BONE PICKER");
    for(int i=0;i<30;++i)size_frame();
    require(ImGui::FindWindowByName("##lite-campaths")->Size.x<260,"Legacy sidebar width does not adopt the narrower default");
    ImGuiWindow* restored_size=nullptr;
    for(auto* window:size_context->Windows)if(window->Active && std::strstr(window->Name,"##attach-card"))restored_size=window;
    if(restored_size && !(std::abs(restored_size->Size.x-resized_expected.x)<1 && std::abs(restored_size->Size.y-resized_expected.y)<1))
        std::fprintf(stderr,"Resized restore expected %.1fx%.1f got %.1fx%.1f main %.1fx%.1f\n",resized_expected.x,resized_expected.y,restored_size->Size.x,restored_size->Size.y,ImGui::FindWindowByName("Deadlock Dolly")->Size.x,ImGui::FindWindowByName("Deadlock Dolly")->Size.y);
    require(restored_size && std::abs(restored_size->Size.x-resized_expected.x)<1 && std::abs(restored_size->Size.y-resized_expected.y)<1,"Resized section dimensions do not survive a fresh UI instance");
    ImGui::LoadIniSettingsFromMemory("[DollyUI][Preferences]\nWidths2=nan,1,1\nHeights2=-10,0,0,0\nColumns2=99,1,-1,-1\n");
    for(int i=0;i<3;++i)size_frame();
    require(std::abs(restored_size->Size.x-resized_expected.x)<1 && std::abs(restored_size->Size.y-resized_expected.y)<1,"Invalid saved sizes overwrite the valid arrangement");
    size_io.IniFilename=nullptr;ImGui::DestroyContext(size_context);ImGui::SetCurrentContext(ctx);
    activate(main,"Export###EXPORT");settle();
    auto* expanded_size=find_card("##export-settings");
    if(!expanded_size->StateStorage.GetInt(expanded_size->GetID("Encoder & quality"),0))activate(expanded_size,"Encoder & quality");
    settle();
    const ImVec2 expanded_edge(expanded_size->Pos.x+expanded_size->Size.x-7,expanded_size->Pos.y+expanded_size->Size.y-7);
    io.AddMousePosEvent(expanded_edge.x,expanded_edge.y);frame();frame();io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(expanded_edge.x,expanded_edge.y+30);frame();frame();io.AddMouseButtonEvent(0,false);settle();
    const float expanded_outer=expanded_size->Size.y;
    activate(expanded_size,"Encoder & quality");settle();
    require(std::abs(expanded_size->Size.y-expanded_outer)<1,"A user-sized expanded section loses its outer height when collapsed");
    ImGui::LoadIniSettingsFromMemory("[DollyUI][Preferences]\nHeights4=0,0,0,0\n");
    activate(main,"Bone Picker###BONE PICKER");settle();
    // A card may be placed in unused column space, not just swapped.
    const auto body=bone_size_card->ParentWindow;
    const ImVec2 empty_from(bone_size_card->Pos.x+20,bone_size_card->Pos.y+15);
    auto* bone_frame_card=find_card("##attach-framing");
    // Restore the extra height first so the two cards can share a tall column.
    ImGui::LoadIniSettingsFromMemory("[DollyUI][Preferences]\nHeights2=0,0,0,0\n");
    ImGui::SetWindowSize(main,ImVec2(940,700));settle();
    const ImVec2 empty_to(bone_frame_card->Pos.x+25,bone_frame_card->Pos.y+bone_frame_card->Size.y+25);
    io.AddMousePosEvent(empty_from.x,empty_from.y);frame();frame();io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(empty_from.x+20,empty_from.y);frame();frame();
    require(ctx->DragDropActive,"Empty placement did not start a section drag");
    io.AddMousePosEvent(empty_to.x,empty_to.y);frame();frame();io.AddMouseButtonEvent(0,false);settle();
    if(!(std::abs(bone_size_card->Pos.x-bone_frame_card->Pos.x)<1 && bone_size_card->Pos.y>bone_frame_card->Pos.y+bone_frame_card->Size.y))
        std::fprintf(stderr,"Empty target %.1f %.1f; bone %.1f %.1f %.1fx%.1f frame %.1f %.1f %.1fx%.1f body %.1fx%.1f\n%s\n",empty_to.x,empty_to.y,bone_size_card->Pos.x,bone_size_card->Pos.y,bone_size_card->Size.x,bone_size_card->Size.y,bone_frame_card->Pos.x,bone_frame_card->Pos.y,bone_frame_card->Size.x,bone_frame_card->Size.y,body->Size.x,body->Size.y,ImGui::SaveIniSettingsToMemory());
    require(std::abs(bone_size_card->Pos.x-bone_frame_card->Pos.x)<1 && bone_size_card->Pos.y>bone_frame_card->Pos.y+bone_frame_card->Size.y,"Empty column space cannot receive a section");
    require(body->Scroll.y==0,"Custom section placement adds scrolling");
    ImGui::SetWindowSize(main,ImVec2(940,520));settle();
    const auto menu_before_matrix=main->Pos,menu_size_before_matrix=main->Size;
    const auto timeline_before_matrix=timeline->Pos,timeline_size_before_matrix=timeline->Size;
    const auto dof_before_reorder=snapshot.dof;
    snapshot.dof={1,1,-100,0,180,1490,-100,0,180,2000,.5};
    unsigned checked_arrangements=0;
    for(const auto viewport : {ImVec2(1280,720),ImVec2(640,480)}) {
        io.DisplaySize=viewport;settle();
        for(int page : {3,4}) {
            activate(main,page==3 ? "Look###LOOK" : "Export###EXPORT");settle();
            auto* advanced=find_card(page==3 ? "##dof-card" : "##export-settings");
            const char* header=page==3 ? "Individual focus overrides" : "Encoder & quality";
            if(!advanced->StateStorage.GetInt(advanced->GetID(header),0))activate(advanced,header);
            settle();
            require(advanced->StateStorage.GetInt(advanced->GetID(header),0),"Permutation fixture failed to expand its controls");
            unsigned order[]={0,1,2,3};
            do {
                char preference[120];std::snprintf(preference,sizeof(preference),"[DollyUI][Preferences]\nSections%d=%u,%u,%u,%u\n",page,order[0],order[1],order[2],order[3]);
                ImGui::LoadIniSettingsFromMemory(preference);settle();
                for(auto* card:ctx->Windows)if(card->Active && card->ParentWindow && std::strstr(card->ParentWindow->Name,"##editor-content")) {
                    require(card->Pos.y+card->Size.y<=card->ParentWindow->InnerClipRect.Max.y+1 && card->ScrollMax.y<=1,
                            "A saved expanded section arrangement clips or scrolls its controls");
                    for(auto* other:ctx->Windows)if(other!=card && other->Active && other->ParentWindow==card->ParentWindow) {
                        const bool overlap=card->Pos.x<other->Pos.x+other->Size.x-1 && other->Pos.x<card->Pos.x+card->Size.x-1 &&
                                           card->Pos.y<other->Pos.y+other->Size.y-1 && other->Pos.y<card->Pos.y+card->Size.y-1;
                        require(!overlap,"Rearranged sections overlap");
                    }
                }
                ++checked_arrangements;
            }while(std::next_permutation(std::begin(order),std::end(order)));
        }
    }
    require(checked_arrangements==96,"Section arrangement coverage is incomplete");
    ImGui::LoadIniSettingsFromMemory("[DollyUI][Preferences]\nSections3=0,1,2,3\nSections4=0,1,2,3\n");
    snapshot.dof=dof_before_reorder;io.DisplaySize=ImVec2(1920,1080);
    ImGui::SetWindowPos(main,menu_before_matrix);ImGui::SetWindowSize(main,menu_size_before_matrix);
    ImGui::SetWindowPos(timeline,timeline_before_matrix);ImGui::SetWindowSize(timeline,timeline_size_before_matrix);settle();activate(main,"Camera###CAMERA");settle();
    std::puts("All96 expanded Look/Export permutations fit without overlap or scrolling at desktop and compact sizes.");
    replay_info_known_stub=false;frame();frame();
    require(panel.timeline_view_end()<=1.1f,"Unknown replay fixture is not bounded");
    replay_info_known_stub=true;settle();
    require(panel.timeline_view_end()>=146925,"Replay metadata arrival leaves the ruler stuck at 0-1");
    activate(main,"Look###LOOK");settle();
    ImGuiWindow* content=nullptr;
    float last_card_bottom=0;
    for(auto* window:ctx->Windows) if(window->Active && window->ParentWindow &&
            std::strstr(window->ParentWindow->Name,"##editor-content")) {
        content=window->ParentWindow;
        last_card_bottom=std::max(last_card_bottom,window->Pos.y+window->Size.y);
    }
    unsigned look_cards=0;
    for(auto* window:ctx->Windows) if(window->Active && window->ParentWindow &&
            std::strstr(window->ParentWindow->Name,"##editor-content")) ++look_cards;
    require(look_cards==4,"Look must display its four control cards without an Effects placeholder");
    require(content && main->Size.y<=520,"The editor footer still hangs below an oversized menu");
    const float matched_height = main->Size.y;
    float matched_font=0;
    for (const char* tab : {"Camera###CAMERA", "Follow###FOLLOW", "Bone Picker###BONE PICKER", "Look###LOOK", "Export###EXPORT"}) {
        activate(main,tab);settle();
        require(std::abs(main->Size.y-matched_height)<1,"Main tabs change the menu height");
        for (auto* card:ctx->Windows) if (card->Active && card->ParentWindow &&
                std::strstr(card->ParentWindow->Name,"##editor-content")) {
            if (!matched_font) matched_font=card->FontRefSize;
            require(std::abs(card->FontRefSize-matched_font)<.1f,"Main tabs use different content font sizes");
        }
    }
    require(main->Size.y<=io.DisplaySize.y-timeline->Size.y-40 && !main->ScrollbarY && main->ScrollMax.y<=1,
            "The continuous editor does not fit its current controls");
    observed_actions.clear();activate(main,"Stop / restore");
    require(ctx->NavWindow==main && ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main].GetWidth()<=160,
            "Stop / restore still stretches across the editor");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::Stop,
            "The compact Stop / restore button lost its existing action");
    activate(main,"Camera###CAMERA");settle();
    activate(timeline,"Play cinematic");
    const auto cinematic_rect=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main];
    require(cinematic_rect.Min.x<260 && cinematic_rect.Min.y<45,
            "Play cinematic must sit next to Replay at the top left");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    activate(timeline,"##next-player");
    const float next_arrow_x=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main].Min.x;
    activate(timeline,"##next-player");
    require(std::abs(ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main].Min.x-next_arrow_x)<.1f,
            "Player name length moves the navigation arrows");
    observed_actions.clear();
    activate(timeline,"< Previous");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::PreviousView,
            "Timeline previous camera button lost the saved-view action");
    const float previous_x=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main].Min.x;
    activate(timeline,"Seek here");
    const float seek_x=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main].Min.x;
    const auto seek_rect=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main];
    require(std::abs((seek_rect.Min.x+seek_rect.Max.x)*.5f+
                        timeline->DC.CursorStartPos.x-timeline->Pos.x-timeline->Size.x*.5f)<2,
            "Seek here is not centered on the timeline");
    observed_actions.clear();activate(timeline,"Resume");
    const auto resume_rect=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main];
    require(resume_rect.Min.y>seek_rect.Max.y && resume_rect.Min.x>timeline->Size.x*.2f,
            "Resume is still isolated from the centered playback controls");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::PlayPause,
            "Relocated Resume lost its replay pause/play action");
    observed_actions.clear();activate(timeline,"Forward >");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::NextView &&
                previous_x<seek_x && seek_x<ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main].Min.x,
            "Camera view buttons do not surround Seek here");
    observed_actions.clear();activate(timeline,"##lite-tick");
    auto tick_rect=ctx->NavWindow->NavRectRel[ImGuiNavLayer_Main];
    tick_rect.Translate(ImVec2(ctx->NavWindow->Pos.x-timeline->Pos.x,
                              ctx->NavWindow->Pos.y-timeline->Pos.y));
    require(tick_rect.Min.x>timeline->Size.x*.7f && tick_rect.Min.y<seek_rect.Min.y,
            "Tick editor must replace the last ruler label at the right end");
    const ImVec2 tick_click(timeline->Pos.x+(tick_rect.Min.x+tick_rect.Max.x)*.5f,
                            timeline->Pos.y+(tick_rect.Min.y+tick_rect.Max.y)*.5f);
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    io.AddMousePosEvent(tick_click.x,tick_click.y);frame();
    io.AddMouseButtonEvent(ImGuiMouseButton_Left,true);frame();
    io.AddMouseButtonEvent(ImGuiMouseButton_Left,false);frame();
    require(ctx->ActiveId==timeline->GetID("##lite-tick"),"Relocated tick field cannot be clicked with the mouse");
    io.AddInputCharactersUTF8("561");frame();
    io.AddKeyEvent(ImGuiKey_Enter,true);frame();io.AddKeyEvent(ImGuiKey_Enter,false);frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SeekReplayTick &&
                observed_actions[0].value==561,"Relocated tick input no longer seeks on Enter");
    observed_actions.clear();
    io.AddKeyEvent(ImGuiKey_Space,true);
    ctx->NavNextActivateId=timeline->GetID("Play cinematic");frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::PrepareCinematic,
            "Cinematic playback starts before replay preparation");
    auto play_count=[&] {
        return std::count_if(observed_actions.begin(),observed_actions.end(),[](const auto& action) {
            return action.action==dolly::EditorAction::PlayPath;
        });
    };
    dolly::cinematic_status_stub.token=unsigned(observed_actions[0].value);
    dolly::cinematic_status_stub.revision=camera_revision_stub;
    dolly::cinematic_status_stub.state=1;
    snapshot.busy=true;frame();frame();
    require(play_count()==0,"Cinematic starts during preparation");
    dolly::cinematic_status_stub.state=2;
    frame();require(play_count()==0,"Cinematic starts while the worker is still busy");
    snapshot.busy=false;frame();frame();frame();
    require(play_count()==1,"Completed preparation must automatically play exactly once");
    const auto* prompt=ImGui::FindWindowByName("##cinematic-ready");
    require(!prompt || !prompt->Active,"Cinematic still requires a Space confirmation");
    io.AddKeyEvent(ImGuiKey_Space,false);frame();
    // An old completion or a canceled/failed seek cannot start playback.
    auto prepare_request=[&] {
        observed_actions.clear();activate(timeline,"Play cinematic");
        require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::PrepareCinematic,
                "Cinematic preparation request is missing");
        return unsigned(observed_actions[0].value);
    };
    auto token=prepare_request();
    dolly::cinematic_status_stub.token=token-1;dolly::cinematic_status_stub.state=2;frame();frame();
    require(play_count()==0,"An old preparation completion starts playback");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    const auto retry_token=prepare_request();
    require(retry_token!=token,"Retrying a canceled preparation reuses its pending token");
    dolly::cinematic_status_stub.token=token;frame();frame();
    require(play_count()==0,"A canceled preparation starts playback during a retry");
    activate(main,"Stop / restore");
    dolly::cinematic_status_stub.token=retry_token;frame();frame();
    require(play_count()==0,"Stop allows a pending preparation to start playback");
    token=prepare_request();
    dolly::cinematic_status_stub.token=token;dolly::cinematic_status_stub.state=3;frame();frame();
    require(play_count()==0,"Failed cinematic preparation starts playback");
    token=prepare_request();
    ++camera_revision_stub;frame();
    dolly::cinematic_status_stub.token=token;dolly::cinematic_status_stub.state=2;frame();frame();
    require(play_count()==0,"An edited path starts an old cinematic request");
    --camera_revision_stub;
    // The marker remains independently clickable with the tracker on its tick,
    // including the closest supported one-tick replay view.
    io.AddMousePosEvent(panel.timeline_x0()+(panel.timeline_x1()-panel.timeline_x0())*4000.f/146925.f,panel.timeline_y());
    io.AddMouseWheelEvent(0,100); frame(); frame();
    require(panel.timeline_view_end()-panel.timeline_view_start()<=1.1f,"Replay cannot zoom to individual ticks");
    const float kill_x=panel.timeline_x0()+(panel.timeline_x1()-panel.timeline_x0())*
                       (4000.f-panel.timeline_view_start())/(panel.timeline_view_end()-panel.timeline_view_start());
    io.AddMousePosEvent(kill_x,panel.timeline_y()-19); frame();frame();
    observed_actions.clear();io.AddMouseButtonEvent(0,true);frame();frame();
    io.AddMouseButtonEvent(0,false);frame();frame();
    if (observed_actions.size()!=1)
        std::fprintf(stderr,"Kill zoom %.3f..%.3f, pointer %.1f %.1f, hovered %s, %zu actions\n",
                     panel.timeline_view_start(),panel.timeline_view_end(),io.MousePos.x,io.MousePos.y,
                     ctx->HoveredWindow ? ctx->HoveredWindow->Name : "none",observed_actions.size());
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SeekReplayTick &&
                observed_actions[0].value==4000,"Playhead or zoom hides the kill marker's hit target");
    // This tick is Ivy's kill of Haze. Both participants retain the hit target,
    // with kill/death colors, while an unrelated selected player must not.
    dolly::replay_third_player_stub=true;
    activate(timeline,"##next-player");
    observed_actions.clear();
    io.AddMousePosEvent(kill_x,panel.timeline_y()-19);frame();frame();
    io.AddMouseButtonEvent(0,true);frame();frame();
    io.AddMouseButtonEvent(0,false);frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SeekReplayTick &&
                observed_actions[0].value==4000,"Selected player's death marker is not clickable");
    activate(timeline,"##next-player");
    observed_actions.clear();
    io.AddMousePosEvent(kill_x,panel.timeline_y()-19);frame();frame();
    io.AddMouseButtonEvent(0,true);frame();frame();
    io.AddMouseButtonEvent(0,false);frame();frame();
    require(observed_actions.empty(),"Unrelated players' events remain clickable after changing player");
    activate(timeline,"##next-player");
    dolly::replay_third_player_stub=false;
    observed_actions.clear();
    io.AddMousePosEvent(kill_x,panel.timeline_y()-19);frame();frame();
    io.AddMouseButtonEvent(0,true);frame();frame();
    io.AddMouseButtonEvent(0,false);frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SeekReplayTick &&
                observed_actions[0].value==4000,"Selecting the killer does not restore their marker");
    // Reloading an equally long replay must discard an old one-tick zoom.
    snapshot.ready=false;frame();frame();
    snapshot.ready=true;frame();frame();
    require(panel.timeline_view_start()==0 && panel.timeline_view_end()==146925,
            "Replay startup retains a previous zoom and hides kill events");
    io.AddMousePosEvent((panel.timeline_x0()+panel.timeline_x1())*.5f,panel.timeline_y());
    io.AddMouseWheelEvent(0,8);frame();frame();
    require(panel.timeline_view_end()-panel.timeline_view_start()<146925,
            "Manual zoom no longer works after initial replay fit");
    dolly::replay_events_status_stub=1;frame();frame();
    dolly::replay_events_status_stub=2;frame();frame();
    require(panel.timeline_view_start()==0 && panel.timeline_view_end()==146925,
            "Newly loaded kill index does not fit all replay events");
    activate(main,"Layout");
    require(!ctx->OpenPopupStack.empty(),"Layout preferences cannot open");
    auto* layout=ctx->OpenPopupStack.back().Window;
    if(paths->Flags&ImGuiWindowFlags_NoMove)activate(layout,"Arrange panels");
    activate(layout,"Reduce motion");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    require(!(paths->Flags&ImGuiWindowFlags_NoMove) && !(timeline->Flags&ImGuiWindowFlags_NoResize),
            "Arrange panels does not unlock the campaths and timeline");
    ImGui::SetWindowSize(main,ImVec2(420,400));settle();
    require(main->Size.x>=640 && main->Size.y>=520,
            "Editor resizing can still shrink controls into tiny text");
    ImGui::SetWindowSize(main,ImVec2(940,520));settle();
    ImGui::SetWindowSize(paths,ImVec2(220,paths->Size.y));settle();
    require(paths->Size.x<260 && paths->Size.x>=220,"Campath sidebar cannot resize down to its readable table minimum");
    const auto* narrow_table=ctx->Tables.GetByKey(paths->GetID("##lite-campath-details"));
    require(narrow_table && narrow_table->Columns[0].WorkMaxX-narrow_table->Columns[0].WorkMinX>=ImGui::CalcTextSize("Camera 64").x+4,
            "Narrow sidebar clips camera names during their slide animation");
    require(narrow_table->Columns[3].WorkMaxX-narrow_table->Columns[3].WorkMinX-4>=ImGui::CalcTextSize("-180.0").x,
            "Narrow sidebar clips valid negative Bank values");
    const auto edge_width=paths->Size.x;
    const ImVec2 edge(paths->Pos.x+paths->Size.x-3,paths->Pos.y+paths->Size.y*.5f);
    io.AddMousePosEvent(edge.x,edge.y);frame();frame();io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(edge.x+60,edge.y);frame();frame();io.AddMouseButtonEvent(0,false);settle();
    require(paths->Size.x>edge_width+40 && paths->Size.x<=360,"Sidebar width grip cannot adjust within its safe limits");
    ImGui::SetWindowSize(paths,ImVec2(edge_width,paths->Size.y));settle();
    // Exercise the real header gesture, then serialize with ImGui's normal
    // settings writer. No project data or real user settings are touched.
    const auto before=paths->Pos;
    io.AddMousePosEvent(before.x+45,before.y+7);frame();
    io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(before.x+105,before.y-23);frame();frame();
    io.AddMouseButtonEvent(0,false);frame();
    if(!(paths->Pos.x>before.x+40))std::fprintf(stderr,"Path drag %.0f %.0f -> %.0f %.0f, main %.0f %.0f size%.0f %.0f, hovered%s, active%u, popups%d, flags%d\n",before.x,before.y,paths->Pos.x,paths->Pos.y,main->Pos.x,main->Pos.y,main->Size.x,main->Size.y,ctx->HoveredWindow ? ctx->HoveredWindow->Name : "none",ctx->ActiveId,ctx->OpenPopupStack.Size,int(paths->Flags));
    require(paths->Pos.x>before.x+40,"Campath handle does not move the panel");
    ImGui::SetWindowSize(timeline,ImVec2(560,180));frame();frame();
    require(!timeline->ScrollbarX && timeline->ScrollMax.x<=1 && !timeline->ScrollbarY,
            "A custom narrow timeline clips or scrolls its transport");
    std::size_t ini_length=0;
    const std::string ini(ImGui::SaveIniSettingsToMemory(&ini_length));
    require(ini.find("[Window][##lite-campaths]")!=std::string::npos &&
                ini.find("[Window][##lite-timeline]")!=std::string::npos &&
                ini.find("ReducedMotion=1")!=std::string::npos,"Panel positions and motion preference do not save");
    const auto saved=paths->Pos;
    ImGui::SetWindowPos(paths,ImVec2(500,50));frame();
    ImGui::LoadIniSettingsFromMemory(ini.c_str(),ini.size());frame();frame();
    require(std::abs(paths->Pos.x-saved.x)<1,"Saved campath position does not restore");
    activate(main,"Layout");layout=ctx->OpenPopupStack.back().Window;
    activate(layout,"Classic arrangement");settle();
    require(paths->Pos.x<25 && main->Pos.x>paths->Pos.x+paths->Size.x &&
                std::abs(main->Pos.x+main->Size.x*.5f-io.DisplaySize.x*.5f)<2 &&
                timeline->Pos.y>main->Pos.y+main->Size.y,
            "Classic arrangement must place campaths left, menu in the middle, and timeline below");
    for(unsigned cameras : {0u,1u,2u,64u}) {
        snapshot.camera_count=cameras;snapshot.selected_camera=0;settle();
        require(paths->DC.CursorMaxPos.y<=paths->InnerClipRect.Max.y+1,
                "The campath Delete/Clear All row is clipped");
    }
    snapshot.camera_count=2;settle();
    activate(main,"Layout");layout=ctx->OpenPopupStack.back().Window;
    if(paths->Flags&ImGuiWindowFlags_NoMove)activate(layout,"Arrange panels");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    ImGui::SetWindowSize(paths,ImVec2(284,442));
    snapshot.camera_count=3;snapshot.selected_camera=2;settle();
    activate(main,"Layout");layout=ctx->OpenPopupStack.back().Window;
    activate(layout,"Reduce motion");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    snapshot.camera_count=4;snapshot.selected_camera=3;
    for (int animation_frame=0;animation_frame<18;++animation_frame) {
        frame();
        const auto rgb=dolly::ui::SELECTED;
        const auto fill=IM_COL32((rgb>>16)&255,(rgb>>8)&255,rgb&255,255);
        for (const auto& vertex:paths->DrawList->VtxBuffer)
            if ((vertex.col&0xffffff)==(fill&0xffffff))
                require(vertex.pos.x<=paths->InnerClipRect.Max.x+1,
                        "A newly placed camera animates its row outside the sidebar bounds");
        require(paths->DC.CursorMaxPos.y<=paths->InnerClipRect.Max.y+1,
                "A newly placed camera clips the sidebar footer while animating");
    }
    settle();
    observed_actions.clear();
    // The filled tail must include Camera 03 after adding Camera 04.
    const int middle_index=2;
    const ImGuiID visible_row_seed=ImHashData(&middle_index,sizeof(middle_index),paths->IDStack.back());
    ctx->NavNextActivateId=ImHashStr("##camera",0,visible_row_seed);frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SelectCamera &&
                observed_actions[0].value==2,"Campath tail does not backfill preceding cameras");
    require(paths->DC.CursorMaxPos.y<=paths->InnerClipRect.Max.y+1,"Four-camera tail clips its footer");
    snapshot.camera_count=2;snapshot.selected_camera=0;settle();
    snapshot.camera_count=32;snapshot.selected_camera=31;settle();
    snapshot.camera_count=33;snapshot.selected_camera=32;camera_first_stub=1;settle();
    observed_actions.clear();
    const int boundary_middle=31;
    const auto boundary_seed=ImHashData(&boundary_middle,sizeof(boundary_middle),paths->ID);
    ctx->NavNextActivateId=ImGui::GetIDWithSeed("##camera",nullptr,boundary_seed);frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SelectCamera &&
                observed_actions[0].value==31,"Camera 33 is isolated from preceding cameras across a wire boundary");
    snapshot.camera_count=2;snapshot.selected_camera=0;camera_first_stub=0;settle();
    // Every tab submits all its cards in one continuous surface, including
    // compact and user-resized workspaces. Advanced controls expand inline.
    io.DisplaySize=ImVec2(640,480);settle();
    io.AddMousePosEvent(main->Pos.x+main->Size.x-main->WindowPadding.x-31,
                       main->Pos.y+main->WindowPadding.y+13);frame();frame();
    io.AddMouseButtonEvent(ImGuiMouseButton_Left,true);frame();
    io.AddMouseButtonEvent(ImGuiMouseButton_Left,false);frame();frame();
    require(!ctx->OpenPopupStack.empty(),"Always-draggable header intercepts the compact Layout button");
    ImGui::ClosePopupToLevel(0,true);frame();
    activate(main,"Layout");layout=ctx->OpenPopupStack.back().Window;
    if(paths->Flags&ImGuiWindowFlags_NoMove)activate(layout,"Arrange panels");
    io.AddKeyEvent(ImGuiKey_Escape,true);frame();io.AddKeyEvent(ImGuiKey_Escape,false);frame();
    ImGui::SetWindowSize(main,ImVec2(520,328));settle();
    const char* tabs[]={"Camera###CAMERA","Follow###FOLLOW","Bone Picker###BONE PICKER","Look###LOOK","Export###EXPORT"};
    const unsigned counts[]={2,2,2,4,4};
    for(unsigned tab=0;tab<5;++tab) {
        activate(main,tabs[tab]);settle();
        unsigned visible=0;
        for(auto* window:ctx->Windows) if(window->Active && window->ParentWindow &&
                std::strstr(window->ParentWindow->Name,"##editor-content")) {
            ++visible;
            if(window->Pos.y+window->Size.y>window->ParentWindow->InnerClipRect.Max.y+1)
                std::fprintf(stderr,"Clipped card %s: bottom %.0f / %.0f\n",window->Name,
                             window->Pos.y+window->Size.y,window->ParentWindow->InnerClipRect.Max.y);
            require(!window->ScrollbarY && window->Scroll.y==0 &&
                        window->Pos.y+window->Size.y<=window->ParentWindow->InnerClipRect.Max.y+1,
                    "Continuous compact controls scroll or clip a card");
        }
        require(visible==counts[tab],"A tab still hides controls behind another section page");
        require(main->DC.CursorMaxPos.y<=main->InnerClipRect.Max.y+1,"Continuous tabs clip their footer");
        const char* card_name=tab==2 ? "##attach-framing" : tab==3 ? "##dof-card" : tab==4 ? "##export-settings" : nullptr;
        if(card_name) {
            ImGuiWindow* advanced=nullptr;
            for(auto* window:ctx->Windows) if(window->Active && std::strstr(window->Name,card_name)) advanced=window;
            require(advanced,"Inline advanced controls are missing");
            const float font_before=advanced->FontRefSize;
            activate(advanced,tab==2 ? "Rotation & transition" : tab==3 ? "Individual focus overrides" : "Encoder & quality");
            if(tab==2) activate(advanced,"Model visibility");
            settle();
            require(std::abs(advanced->FontRefSize-font_before)<.1f,"Expanding inline controls changes the UI font size");
            for(auto* window:ctx->Windows) if(window->Active && window->ParentWindow &&
                    std::strstr(window->ParentWindow->Name,"##editor-content"))
                require(window->Pos.y+window->Size.y<=window->ParentWindow->InnerClipRect.Max.y+1 && window->Scroll.y==0,
                        "Expanded inline controls clip or require scrolling");
        }
    }
    // Near a fitting boundary, font rounding/text wrapping must not alternate
    // the layout height and intermittently clip the footer or a card.
    for(const auto viewport : {ImVec2(600,900),ImVec2(800,600),ImVec2(1280,720)}) {
        io.DisplaySize=viewport;
        settle();
        activate(main,"Layout");layout=ctx->OpenPopupStack.back().Window;
        activate(layout,"Classic arrangement");
        activate(main,viewport.x<=800 ? "Look###LOOK" : "Export###EXPORT");
        settle();
        const char* header=viewport.x<=800 ? "Individual focus overrides" : "Encoder & quality";
        const char* card_name=viewport.x<=800 ? "##dof-card" : "##export-settings";
        ImGuiWindow* advanced=nullptr;
        for(auto* window:ctx->Windows) if(window->Active && std::strstr(window->Name,card_name)) advanced=window;
        if(advanced && advanced->StateStorage.GetInt(advanced->GetID(header),0)) activate(advanced,header);
        settle();
        for(int stable_frame=0;stable_frame<20;++stable_frame) {
            frame();
            require(main->DC.CursorMaxPos.y<=main->InnerClipRect.Max.y+1,
                    "Tab fitting oscillates and clips its footer");
            for(auto* window:ctx->Windows) if(window->Active && window->ParentWindow &&
                    std::strstr(window->ParentWindow->Name,"##editor-content"))
                require(window->Pos.y+window->Size.y<=window->ParentWindow->InnerClipRect.Max.y+1,
                        "Tab fitting oscillates and clips a card");
        }
    }
    io.DisplaySize=ImVec2(1280,720);
    snapshot.camera_count=40;snapshot.selected_camera=33;camera_first_stub=32;settle();
    ImGui::SetWindowPos(paths,ImVec2(16,20));settle();
    observed_actions.clear();activate(paths,"##previous-cameras");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::CameraPage &&
                observed_actions[0].value==0,"Previous campath block does not request its destination");
    // Leave the outgoing partial block published for several frames before
    // acknowledging, just as the real desktop round trip does.
    for(int i=0;i<10;++i) frame();
    camera_first_stub=0;settle();observed_actions.clear();
    const int last_camera=31;
    const auto row_seed=ImHashData(&last_camera,sizeof(last_camera),paths->ID);
    ctx->NavNextActivateId=ImGui::GetIDWithSeed("##camera",nullptr,row_seed);frame();frame();
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SelectCamera &&
                observed_actions[0].value==31,"A delayed previous-block acknowledgement loses the last camera page");
    camera_first_stub=32;settle();observed_actions.clear();
    // The shorter custom panel has more local pages within a wire block.
    // Reach the block boundary before testing a stale request rejection.
    for(int i=0;i<8 && observed_actions.empty();++i) activate(paths,"##previous-cameras");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::CameraPage &&
                observed_actions[0].revision==7,"Stale-page fixture did not reach its block boundary");
    camera_revision_stub=8;frame();frame();
    // A prior Arrive/Bank/Undo can reject the queued page's old revision.
    // The current block stays put; its navigation must become available again.
    observed_actions.clear();activate(paths,"##previous-cameras");
    require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::CameraPage &&
                observed_actions[0].revision==8,"A rejected stale page permanently disables campath navigation");
    camera_revision_stub=7;
    camera_first_stub=0;
    std::puts("UI rework: individual kill ticks, movable/saved panels, corrected Classic preset, continuous tabs and unclipped campath footer passed.");
    ImGui::DestroyContext(ctx); ImGui::SetCurrentContext(previous); snapshot=original;
}
int main(int argc, char** argv) {
    try {
        SetEnvironmentVariableA("DOLLY_UI_LAYOUT_FILE", "none");
        const bool lite_flight_screenshot = argc == 3 && std::strcmp(argv[1], "--screenshot-lite-flight") == 0;
        const bool lite_replay_screenshot = argc == 3 && std::strcmp(argv[1], "--screenshot-lite-replay") == 0;
        const bool lite_screenshot = lite_replay_screenshot || lite_flight_screenshot || (argc == 3 && std::strcmp(argv[1], "--screenshot-lite") == 0);
        // The reworked editor must be the default with no opt-in environment or launch flag.
        SetEnvironmentVariableA("DOLLY_LITE_UI", nullptr);
        const bool follow_screenshot = argc == 3 && std::strcmp(argv[1], "--screenshot-follow") == 0;
        const bool bone_screenshot = argc == 3 && std::strcmp(argv[1], "--screenshot-bone") == 0;
        const bool lens_screenshot = argc == 3 && std::strcmp(argv[1], "--screenshot-lens") == 0;
        const bool export_screenshot =
            argc == 3 && std::strcmp(argv[1], "--screenshot-export") == 0;
        const bool object_screenshot =
            argc == 3 && std::strcmp(argv[1], "--screenshot-object") == 0;
        const bool screenshot = follow_screenshot || bone_screenshot || lite_screenshot || lens_screenshot || export_screenshot || object_screenshot ||
                                (argc == 3 && std::strcmp(argv[1], "--screenshot") == 0);
        const bool layout_screenshot = screenshot && std::getenv("DOLLY_UI_TEST_LAYOUT");
        unsigned render_width = lite_screenshot ? 1920 : 800;
        unsigned render_height = lite_screenshot ? 1080 : (screenshot ? 1100 : 600);
        if (layout_screenshot) {
            if (const auto* width = std::getenv("DOLLY_UI_TEST_WIDTH"))
                render_width = unsigned(std::clamp(std::atoi(width), 640, 3840));
            if (const auto* height = std::getenv("DOLLY_UI_TEST_HEIGHT"))
                render_height = unsigned(std::clamp(std::atoi(height), 480, 2160));
        }
        dolly::reshade_set_enabled(false);
        require(!dolly::reshade_overlay_pending() && !dolly::reshade_overlay_open() &&
                    !dolly::reshade_available(),
                "An unconfigured optional ReShade runtime must not hide the editor");
        require(!dolly::reshade_request_overlay(true),
                "Opening absent ReShade must leave ordinary editor input available");
        const auto instance = GetModuleHandleW(nullptr);
        WNDCLASSW wc{};
        wc.lpfnWndProc = DefWindowProcW;
        wc.hInstance = instance;
        wc.lpszClassName = L"Dolly.Overlay.Smoke";
        require(RegisterClassW(&wc) != 0, "Could not register synthetic window");
        HWND window =
            CreateWindowExW(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, wc.lpszClassName, L"Dolly graphics smoke", WS_OVERLAPPEDWINDOW, 32,
                            32, 800, screenshot ? 1100 : 600, nullptr, nullptr, instance, nullptr);
        require(window != nullptr, "Could not create synthetic window");
        if(lite_screenshot || layout_screenshot){RECT r{0,0,LONG(render_width),LONG(render_height)};AdjustWindowRect(&r,WS_OVERLAPPEDWINDOW,FALSE);SetWindowPos(window,nullptr,0,0,r.right-r.left,r.bottom-r.top,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE);}
        // Overlay discovery requires a visible window. Offline runs move this
        // non-activating test surface off screen instead of taking game focus.
        if (GetEnvironmentVariableA("DOLLY_UI_TEST_HIDDEN", nullptr, 0))
            SetWindowPos(window, nullptr, -32000, -32000, 0, 0,
                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
        ShowWindow(window, SW_SHOWNOACTIVATE);
        UpdateWindow(window);
        const auto before_proc = GetWindowLongPtrW(window, GWLP_WNDPROC);
        DXGI_SWAP_CHAIN_DESC desc{};
        desc.BufferCount = 1;
        desc.BufferDesc.Width = render_width;
        desc.BufferDesc.Height = render_height;
        desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.OutputWindow = window;
        desc.SampleDesc.Count = 1;
        desc.Windowed = TRUE;
        desc.SwapEffect = DXGI_SWAP_EFFECT_SEQUENTIAL;
        IDXGISwapChain* chain = nullptr;
        ID3D11Device* device = nullptr;
        ID3D11DeviceContext* context = nullptr;
        const D3D_FEATURE_LEVEL feature = D3D_FEATURE_LEVEL_11_0;
        require(SUCCEEDED(D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0,
                                                        &feature, 1, D3D11_SDK_VERSION, &desc,
                                                        &chain, &device, nullptr, &context)),
                "WARP DX11 device creation failed");
        // Optional graphics diagnostics must stay inside their unused block and
        // fail closed on an unrecognized renderer, without changing camera state.
        std::vector<unsigned char> diagnostic_memory(dolly::kMappingBytes, 0xa5);
        for (const auto& profile : dolly::kRendererDiagnosticLayouts) {
            require(dolly::renderer_diagnostic_layout(profile.hash, profile.image_size,
                                                      profile.timestamp) == &profile,
                    "Reviewed renderer diagnostic layout did not resolve");
            require(!dolly::renderer_diagnostic_layout(profile.hash, profile.image_size + 1,
                                                       profile.timestamp) &&
                        !dolly::renderer_diagnostic_layout(profile.hash, profile.image_size,
                                                           profile.timestamp + 1) &&
                        !dolly::renderer_diagnostic_layout("unknown", profile.image_size,
                                                           profile.timestamp),
                    "Renderer diagnostic layout accepted changed identity metadata");
        }
        dolly::renderer_diagnostics_probe(0, "");
        dolly::renderer_diagnostics_tick(diagnostic_memory.data());
        dolly::RendererDiagnostics diagnostic{};
        std::memcpy(&diagnostic, diagnostic_memory.data() + dolly::kRendererDiagnosticsOffset,
                    sizeof(diagnostic));
        require(std::memcmp(diagnostic.magic, "DLYGFX01", 8) == 0 &&
                    diagnostic.abi == dolly::kRendererDiagnosticsAbi && !(diagnostic.sequence & 1),
                "Optional renderer diagnostic header is invalid");
        require(diagnostic.state == std::uint32_t(dolly::RendererProbeState::Waiting),
                "Missing renderer should leave the optional probe waiting");
        for (std::size_t i = 0; i < diagnostic_memory.size(); ++i)
            if (i < dolly::kRendererDiagnosticsOffset ||
                i >= dolly::kRendererDiagnosticsOffset + sizeof(diagnostic))
                require(diagnostic_memory[i] == 0xa5,
                        "Graphics diagnostics overwrote camera/editor mapping data");
        dolly::renderer_diagnostics_probe(
            reinterpret_cast<std::uintptr_t>(GetModuleHandleW(L"kernel32.dll")), "unknown");
        Sleep(1050); // one bounded sample interval; the probe never polls per frame
        dolly::renderer_diagnostics_tick(diagnostic_memory.data());
        std::memcpy(&diagnostic, diagnostic_memory.data() + dolly::kRendererDiagnosticsOffset,
                    sizeof(diagnostic));
        require(diagnostic.state == std::uint32_t(dolly::RendererProbeState::Unsupported) &&
                    diagnostic.sample == 2,
                "Unrecognized module must not permit private renderer reads");
        require(MH_Initialize() == MH_OK, "MinHook initialization failed");
        require(dolly::install_overlay_hooks(), "DXGI public-method hook installation failed");
        snapshot.enabled = true;
        snapshot.focused = true;
        snapshot.ready = true;
        snapshot.paused = true;
        snapshot.manual_active = true;
        snapshot.horizontal_fov = 90;
        snapshot.view_width = 800;
        snapshot.view_height = 600;
        snapshot.pose = {0, 0, 0, 0, 0, 0, 4.0 / 3.0};
        SyntheticViewer viewer;
        snapshot.owner = dolly::EditorOwner::Panel;
        snapshot.camera_count = 2;
        if(lite_screenshot){snapshot.tick=3470;snapshot.view_width=1920;snapshot.view_height=1080;}
        if (layout_screenshot) {
            snapshot.tick = 3470;
            snapshot.view_width = render_width;
            snapshot.view_height = render_height;
            if (const auto* count = std::getenv("DOLLY_UI_TEST_CAMERAS"))
                snapshot.camera_count = unsigned(std::clamp(std::atoi(count), 0, 128));
        }
        if (screenshot) {
            snapshot.dof_available = true;
            snapshot.dof = {1, 1, -100, 0, 180, 1490, -100, 0, 180, 2000, .5};
            snapshot.attach_available = true;
            snapshot.attach_selected = true;
            snapshot.attach_keys = 2;
            snapshot.shot_keys = 2;
            snapshot.attach_target_index = 0;
            snapshot.attach_point = 0;
            snapshot.attach_offsets[2] = 6.0;
            snapshot.attach_smoothing = .15;
            snapshot.roster_count = 1;
            snapshot.follow_available = true;
            snapshot.citadel_dof_available = true;
            snapshot.citadel_dof_enabled = true;
        }
        if (object_screenshot) {
            // Render the Object Picker with a few placed objects so the whole
            // right-side panel (library, placed list, place/snap/tool/drop rows)
            // can be reviewed visually for clipping.
            snapshot.object_picker = true;
            snapshot.object_distance = 600.0;
            snapshot.object_count = 3;
            snapshot.object_selected = 1;
            for (std::uint32_t i = 0; i < snapshot.object_count; ++i) {
                snapshot.object_items[i] = {};
                snapshot.object_items[i].shape = i + 3;  // crate, barrel, pillar
                snapshot.object_items[i].scale = 1.0f;
                snapshot.object_items[i].position[0] = 400.0f + 200.0f * i;
                snapshot.object_items[i].position[1] = 0.0f;
                snapshot.object_items[i].position[2] = 0.0f;
            }
        }
        snapshot.duration = layout_screenshot && snapshot.camera_count > 2 ? (snapshot.camera_count - 1) * 3 : 3;
        std::snprintf(snapshot.shot_name, sizeof(snapshot.shot_name), "Synthetic editor smoke");
        ID3D11Texture2D* backbuffer = nullptr;
        ID3D11RenderTargetView* target = nullptr;
        require(SUCCEEDED(chain->GetBuffer(0, __uuidof(ID3D11Texture2D),
                                           reinterpret_cast<void**>(&backbuffer))),
                "Backbuffer unavailable");
        require(SUCCEEDED(device->CreateRenderTargetView(backbuffer, nullptr, &target)),
                "Render target creation failed");
        const FLOAT clear[4] = {lite_screenshot||layout_screenshot?0.f:.04f, lite_screenshot||layout_screenshot?0.f:.08f, lite_screenshot||layout_screenshot?0.f:.95f, 1};
        D3D11_VIEWPORT original_viewport{7, 9, 113, 127, .1f, .8f};
        for (int i = 0; i < 3; ++i) {
            MSG message{};
            while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            context->ClearRenderTargetView(target, clear);
            context->OMSetRenderTargets(1, &target, nullptr);
            context->RSSetViewports(1, &original_viewport);
            require(SUCCEEDED(chain->Present(0, 0)), "Synthetic Present failed");
            if (i == 0 && !object_screenshot && (!lite_screenshot || layout_screenshot)) {
                // All camera tools must be present in the default editor.
                ImGui::SetCurrentContext(screenshot_context);
                require(ImGui::FindWindowByName("Deadlock Dolly") != nullptr,
                        "Default full editor missing");
                auto* transport = ImGui::FindWindowByName("##lite-timeline");
                require(transport != nullptr, "Shared transport missing");
                screenshot_context->NavNextActivateId = transport->GetID("Replay###lite-timeline-mode");
                require(SUCCEEDED(chain->Present(0, 0)), "Shot transport activation failed");
                require(SUCCEEDED(chain->Present(0, 0)), "Shot transport render failed");
            }
            if (screenshot && i == 0 && !object_screenshot && (!lite_screenshot || layout_screenshot)) {
                const char* page =
                    lens_screenshot ? "LOOK" : (export_screenshot ? "EXPORT" : "CAMERA");
                require(screenshot_context != nullptr, "Overlay ImGui context missing");
                auto* panel = ImGui::FindWindowByName("Deadlock Dolly");
                require(panel != nullptr, "Editor screenshot panel missing");
                const char* label = lens_screenshot ? "Look###LOOK" : (export_screenshot ? "Export###EXPORT" :
                    (follow_screenshot ? "Follow###FOLLOW" : (bone_screenshot ? "Bone Picker###BONE PICKER" : "Camera###CAMERA")));
                screenshot_context->NavNextActivateId = panel->GetID(label);
            }
        }
        if (layout_screenshot && lite_replay_screenshot) {
            auto* transport=ImGui::FindWindowByName("##lite-timeline");
            screenshot_context->NavNextActivateId=transport->GetID("Campaths###lite-timeline-mode");
            for (int i=0;i<3;++i) require(SUCCEEDED(chain->Present(0,0)),"Replay fixture render failed");
        }
        if (layout_screenshot && std::getenv("DOLLY_UI_TEST_ADVANCED") &&
            (lens_screenshot || export_screenshot)) {
            ImGui::SetCurrentContext(screenshot_context);
            auto* main = ImGui::FindWindowByName("Deadlock Dolly");
            auto render_fixture = [&] {
                context->ClearRenderTargetView(target, clear);
                context->OMSetRenderTargets(1, &target, nullptr);
                context->RSSetViewports(1, &original_viewport);
                require(SUCCEEDED(chain->Present(0, 0)), "Advanced fixture Present failed");
            };
            screenshot_context->NavNextActivateId=main->GetID("Layout");render_fixture();render_fixture();
            auto* layout=screenshot_context->OpenPopupStack.back().Window;
            screenshot_context->NavNextActivateId=layout->GetID("Arrange panels");render_fixture();render_fixture();
            ImGui::GetIO().AddKeyEvent(ImGuiKey_Escape,true);render_fixture();
            ImGui::GetIO().AddKeyEvent(ImGuiKey_Escape,false);render_fixture();
            ImGui::ClosePopupToLevel(0,true);render_fixture();
            ImGui::SetWindowSize(main, ImVec2(740, 820));
            for (int i = 0; i < 3; ++i) render_fixture();
            const char* card_name = lens_screenshot ? "##dof-card" : "##export-settings";
            ImGuiWindow* card = nullptr;
            for (auto* window : screenshot_context->Windows)
                if (std::strstr(window->Name, card_name)) card = window;
            require(card != nullptr, "Advanced fixture card missing");
            screenshot_context->NavNextActivateId = card->GetID(
                lens_screenshot ? "Individual focus overrides" : "Encoder & quality");
            for (int i = 0; i < 3; ++i) render_fixture();
        }
        if (lite_screenshot && !layout_screenshot) {
            ImGui::SetCurrentContext(screenshot_context);
            auto* campaths = ImGui::FindWindowByName("##lite-campaths");
            require(campaths && campaths->Active, "Campaths missing with the menu open");
            require(screenshot_context->Tables.GetByKey(campaths->GetID("##lite-campath-details")),
                    "Campaths must match the compact four-column reference table");
            const auto old_snapshot = snapshot;
            snapshot.enabled = false;
            snapshot.owner = dolly::EditorOwner::Disabled;
            shader_loading_stub = true;
            require(SUCCEEDED(chain->Present(0,0)), "Shader notice Present failed");
            auto* notice = ImGui::FindWindowByName("##shader-loading");
            require(notice && notice->Active && (notice->Flags & ImGuiWindowFlags_NoInputs),
                    "Shader notice must render without menu or editor input");
            shader_loading_stub = false;
            snapshot = old_snapshot;
            require(SUCCEEDED(chain->Present(0,0)), "Shader notice clear Present failed");
            require(!notice->Active, "Shader notice persisted after preload finished");
            auto render_lite = [&] {
                context->ClearRenderTargetView(target,clear);
                context->OMSetRenderTargets(1,&target,nullptr);
                context->RSSetViewports(1,&original_viewport);
                require(SUCCEEDED(chain->Present(0,0)),"Lite timeline Present failed");
            };
            auto* timeline_window = ImGui::FindWindowByName("##lite-timeline");
            require(timeline_window, "Lite controls missing");
            const auto replay_rect=dolly::overlay_diagnostics();
            observed_actions.clear();
            auto& replay_io=ImGui::GetIO();
            replay_io.AddMousePosEvent(replay_rect.timeline_x0+(replay_rect.timeline_x1-replay_rect.timeline_x0)*.6f,replay_rect.timeline_y);
            replay_io.AddMouseButtonEvent(0,true); render_lite(); render_lite();
            replay_io.AddMouseButtonEvent(0,false); render_lite(); render_lite();
            require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SeekReplayTick &&
                    observed_actions[0].value>50000 && observed_actions[0].value<100000,
                    "Default Replay timeline did not seek across the full replay tick range");
            screenshot_context->NavNextActivateId = timeline_window->GetID("Replay###lite-timeline-mode");
            render_lite(); render_lite();
            const auto shot_rect = dolly::overlay_diagnostics();
            require(shot_rect.timeline_x1 > shot_rect.timeline_x0 && shot_rect.timeline_y > 0 &&
                    shot_rect.timeline_y > 900, "Shot controls did not move into the timeline");
            auto* lite_main = ImGui::FindWindowByName("Deadlock Dolly");
            require(lite_main != nullptr, "Lite menu missing");
            ImGui::FocusWindow(lite_main);
            ImGui::ClearActiveID();
            render_lite(); render_lite();
            const auto prior_focus = screenshot_context->NavId;
            dolly::overlay_raw_key(VK_TAB, 0x0f, true);
            for (int i=0;i<6;i++) render_lite();
            require(!ImGui::IsKeyDown(ImGuiKey_Tab) && screenshot_context->NavId == prior_focus &&
                    screenshot_context->ActiveId == 0, "Holding Tab selected Lite controls");
            dolly::overlay_raw_key(VK_TAB, 0x0f, false);
            render_lite();
            observed_actions.clear();
            auto& lite_io = ImGui::GetIO();
            lite_io.AddMousePosEvent((shot_rect.timeline_x0+shot_rect.timeline_x1)*.5f,shot_rect.timeline_y);
            lite_io.AddMouseButtonEvent(0,true);render_lite();render_lite();
            lite_io.AddMouseButtonEvent(0,false);render_lite();render_lite();
            require(observed_actions.empty(),"Shot slider must wait for Seek here before seeking");
            screenshot_context->NavNextActivateId = timeline_window->GetID("Seek here");
            render_lite();render_lite();
            require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SeekShot &&
                    observed_actions[0].value>0 && observed_actions[0].value<snapshot.duration,
                    "Lite Seek here failed to apply the selected shot time");
            observed_actions.clear();
            screenshot_context->NavNextActivateId = timeline_window->GetID("0.25x");
            render_lite(); render_lite();
            require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::SetPlaybackSpeed &&
                    observed_actions[0].value==.25, "0.25x did not set playback speed");
            snapshot.playback_speed=.25;
            render_lite();
            const auto rgb=dolly::ui::SELECTED_BLUE;
            const auto blue=IM_COL32((rgb>>16)&255,(rgb>>8)&255,rgb&255,255);
            bool blue_fill=false;
            for(const auto& vertex : timeline_window->DrawList->VtxBuffer)
                if(vertex.col==blue)blue_fill=true;
            require(blue_fill,"Selected 0.25x speed lacks its blue highlight");
            observed_actions.clear();
            auto* camera_table=screenshot_context->Tables.GetByKey(campaths->GetID("##lite-campath-details"));
            require(camera_table && camera_table->ColumnsCount==4,"Camera table is missing");
            float arrive_x=(camera_table->Columns[1].WorkMinX+camera_table->Columns[1].WorkMaxX)*.5f;
            float arrive_y=camera_table->OuterRect.Min.y+camera_table->InstanceDataFirst.LastTopHeadersRowHeight+camera_table->RowMinHeight*1.5f;
            lite_io.AddMousePosEvent(arrive_x,arrive_y);
            lite_io.AddKeyEvent(ImGuiMod_Ctrl,true);
            lite_io.AddMouseButtonEvent(0,true);render_lite();render_lite();
            lite_io.AddMouseButtonEvent(0,false);render_lite();
            lite_io.AddKeyEvent(ImGuiMod_Ctrl,false);render_lite();
            require(screenshot_context->ActiveId && screenshot_context->InputTextState.ID==screenshot_context->ActiveId,
                    "Lite Arrive/s Ctrl-click did not open a numeric editor");
            // A different edit or an acknowledgement can arrive while this
            // field owns a typed draft. Keep the original gesture revision so
            // authoritative dispatch can reject a stale camera index.
            camera_revision_stub = 8;
            render_lite();
            lite_io.AddInputCharactersUTF8("1.25");render_lite();
            lite_io.AddKeyEvent(ImGuiKey_Enter,true);render_lite();
            lite_io.AddKeyEvent(ImGuiKey_Enter,false);render_lite();render_lite();
            unsigned arrival_edits = 0;
            for(const auto& edit : observed_actions)
                if(edit.action==dolly::EditorAction::SetCameraTime) {
                    require(edit.value==1 && edit.revision==7 && std::abs(edit.time-1.25)<.001,
                            "Arrive edit lost the camera index, revision, or typed time");
                    ++arrival_edits;
                }
            require(arrival_edits==1,"Arrive edit must commit exactly once");
            camera_revision_stub = 7;
            render_lite();
            observed_actions.clear();
            lite_io.MouseClickedTime[0] = -1e30; // A new drag, rather than the editor's double-click shortcut.
            // Temp-input exit can settle the auto-sized card on the following
            // frame. Read its current field geometry before a new gesture.
            render_lite();render_lite();
            arrive_x=(camera_table->Columns[1].WorkMinX+camera_table->Columns[1].WorkMaxX)*.5f;
            arrive_y=camera_table->OuterRect.Min.y+camera_table->InstanceDataFirst.LastTopHeadersRowHeight+camera_table->RowMinHeight*1.5f;
            lite_io.AddMousePosEvent(arrive_x,arrive_y);
            lite_io.AddMouseButtonEvent(0,true);render_lite();render_lite();
            lite_io.AddMousePosEvent(arrive_x+16,arrive_y);render_lite();render_lite();
            lite_io.AddMouseButtonEvent(0,false);render_lite();render_lite();
            unsigned arrival_drags = 0;
            for(const auto& edit : observed_actions)
                if(edit.action==dolly::EditorAction::SetCameraTime) {
                    require(edit.value==1 && edit.revision==7 && edit.time>1.25,
                            "Arrive drag failed to increase the chosen camera time");
                    ++arrival_drags;
                }
            if(arrival_drags!=1)std::fprintf(stderr,"Arrive drag: %u edits, %zu actions at %.1f %.1f\n",arrival_drags,observed_actions.size(),arrive_x,arrive_y);
            require(arrival_drags==1,"Arrive drag must commit once on release");

            snapshot.owner = dolly::EditorOwner::Flight;
            // Replay playback disables path guides too: campaths alone must keep
            // the render path alive without bringing back the main menu.
            snapshot.playing = true;
            for (int i=0;i<3;i++) {
                context->ClearRenderTargetView(target,clear);
                context->OMSetRenderTargets(1,&target,nullptr);
                context->RSSetViewports(1,&original_viewport);
                require(SUCCEEDED(chain->Present(0,0)),"Campath flight Present failed");
            }
            ImGui::SetCurrentContext(screenshot_context);
            campaths = ImGui::FindWindowByName("##lite-campaths");
            require(campaths && campaths->Active && campaths->LastFrameActive == screenshot_context->FrameCount, "Campaths vanished when main menu closed");
            require((campaths->Flags & ImGuiWindowFlags_NoInputs) == ImGuiWindowFlags_NoInputs,
                    "Flight campaths must not capture game input");
            auto* timeline = ImGui::FindWindowByName("##lite-timeline");
            require(timeline && timeline->Active && timeline->LastFrameActive == screenshot_context->FrameCount,
                    "Timeline vanished when main menu closed");
            require((timeline->Flags & ImGuiWindowFlags_NoInputs) == ImGuiWindowFlags_NoInputs,
                    "Flight timeline must not capture game input");
            auto* main = ImGui::FindWindowByName("Deadlock Dolly");
            require(main && !main->Active,"Flight campaths reopened the main menu");
            snapshot.playing = false;
            snapshot.owner = lite_flight_screenshot ? dolly::EditorOwner::Flight : dolly::EditorOwner::Panel;
            if (lite_replay_screenshot) {
                screenshot_context->NavNextActivateId = timeline_window->GetID("Campaths###lite-timeline-mode");
                render_lite(); render_lite();
            }
            for(int i=0;i<3;i++) {
                context->ClearRenderTargetView(target,clear);
                context->OMSetRenderTargets(1,&target,nullptr);
                context->RSSetViewports(1,&original_viewport);
                require(SUCCEEDED(chain->Present(0,0)),"Campath restore Present failed");
            }
            std::puts("Lite campaths and timeline remain visible with the menu closed and do not capture flight input.");
        }
        require(available && attached == window,
                "Overlay did not attach to the presenting game window");
        if(screenshot && layout_screenshot)if(const auto* preferences=std::getenv("DOLLY_UI_TEST_CUSTOM_LAYOUT_FILE")) {
            ImGui::LoadIniSettingsFromDisk(preferences);
            for(int i=0;i<5;++i)require(SUCCEEDED(chain->Present(0,0)),"Custom layout capture failed to render");
        }
        if (screenshot && layout_screenshot && std::getenv("DOLLY_UI_TEST_SWAP_SECTIONS")) {
            static constexpr const char* names[5][4]={{"##cameras-card","##flight-card",nullptr,nullptr},{"##follow-card","##follow-framing",nullptr,nullptr},
                {"##attach-card","##attach-framing",nullptr,nullptr},{"##dof-card","##citadel-dof-card","##appearance-card","##confetti-card"},
                {"##export-camera","##export-settings","##export-passes","##video-card"}};
            const int page=lens_screenshot ? 3 : export_screenshot ? 4 : bone_screenshot ? 2 : follow_screenshot ? 1 : 0;
            unsigned source_index=0,target_index=0;
            require(std::sscanf(std::getenv("DOLLY_UI_TEST_SWAP_SECTIONS"),"%u,%u",&source_index,&target_index)==2 &&
                    source_index<(page>=3 ? 4u : 2u) && target_index<(page>=3 ? 4u : 2u),"Invalid section swap capture fixture");
            auto find_section=[&](unsigned index) -> ImGuiWindow* {
                for(auto* item:screenshot_context->Windows)if(item->Active && std::strstr(item->Name,names[page][index]))return item;
                return nullptr;
            };
            auto render_section=[&] {context->ClearRenderTargetView(target,clear);context->OMSetRenderTargets(1,&target,nullptr);
                context->RSSetViewports(1,&original_viewport);require(SUCCEEDED(chain->Present(0,0)),"Section swap capture failed to render");};
            Sleep(260);render_section();
            auto* arrange_main=ImGui::FindWindowByName("Deadlock Dolly");
            screenshot_context->NavNextActivateId=arrange_main->GetID("Layout");render_section();render_section();
            auto* arrange_window=screenshot_context->OpenPopupStack.back().Window;
            if(arrange_main->Flags&ImGuiWindowFlags_NoResize) {
                screenshot_context->NavNextActivateId=arrange_window->GetID("Arrange panels");render_section();render_section();
            }
            ImGui::ClosePopupToLevel(0,true);render_section();render_section();
            auto* source=find_section(source_index);auto* destination=find_section(target_index);
            require(source && destination,"Section swap capture fixture lost a section");
            const ImVec2 from(source->Pos.x+source->Size.x-9,source->Pos.y+source->WindowPadding.y+7);
            const ImVec2 to(destination->Pos.x+destination->WindowPadding.x+12,destination->Pos.y+destination->WindowPadding.y+7);
            auto& section_io=ImGui::GetIO();section_io.AddMousePosEvent(from.x,from.y);render_section();render_section();
            section_io.AddMouseButtonEvent(ImGuiMouseButton_Left,true);render_section();
            section_io.AddMousePosEvent(from.x+20,from.y);render_section();render_section();
            if(!screenshot_context->DragDropActive)
                std::fprintf(stderr,"Drag page %d source %s %.1f %.1f %.1fx%.1f from %.1f %.1f mouse %.1f %.1f active %u hovered %s main-resize %d parent clip %.1f %.1f %.1f %.1f\n",page,source->Name,source->Pos.x,source->Pos.y,source->Size.x,source->Size.y,from.x,from.y,section_io.MousePos.x,section_io.MousePos.y,screenshot_context->ActiveId,screenshot_context->HoveredWindow ? screenshot_context->HoveredWindow->Name : "none",!(arrange_main->Flags&ImGuiWindowFlags_NoResize),source->ParentWindow->ClipRect.Min.x,source->ParentWindow->ClipRect.Min.y,source->ParentWindow->ClipRect.Max.x,source->ParentWindow->ClipRect.Max.y);
            require(screenshot_context->DragDropActive,"Rendered section capture did not start a drag");
            section_io.AddMousePosEvent(to.x,to.y);render_section();render_section();
            if(!std::getenv("DOLLY_UI_TEST_DRAG_GHOST")) {
            section_io.AddMouseButtonEvent(ImGuiMouseButton_Left,false);render_section();render_section();
            section_io.AddMousePosEvent(-100,-100);render_section();
            std::size_t saved_length=0;const std::string saved(ImGui::SaveIniSettingsToMemory(&saved_length));
            char expected[80];unsigned slots[]={0,1,2,3};std::swap(slots[source_index],slots[target_index]);
            std::snprintf(expected,sizeof(expected),"Sections%d=%u,%u,%u,%u",page,slots[0],slots[1],slots[2],slots[3]);
            require(saved.find(expected)!=std::string::npos,"Rendered section drag did not save the selected arrangement");
            }
        }
        if (screenshot) {
            const bool add_camera=std::getenv("DOLLY_UI_TEST_ADD_CAMERA")!=nullptr;
            if (add_camera) {
                ++snapshot.camera_count;snapshot.selected_camera=snapshot.camera_count-1;
                ++camera_revision_stub;
                snapshot.duration=(snapshot.camera_count-1)*3;
            } else if(const auto* elapsed=std::getenv("DOLLY_UI_TEST_REORDER_CAPTURE_MS")) Sleep(DWORD(std::clamp(std::atoi(elapsed),0,300)));
            else Sleep(260); // Capture the settled endpoint of presentation animations.
            // Nested auto-fit windows apply measured content sizes on the next
            // frame. Let those frames settle too before inspecting pixels.
            for(int i=0;i<(add_camera ? 2 : 8);++i) {
                context->ClearRenderTargetView(target,clear);
                context->OMSetRenderTargets(1,&target,nullptr);
                require(SUCCEEDED(chain->Present(0,0)),"Settled screenshot Present failed");
            }
        }
        ID3D11RenderTargetView* after_target = nullptr;
        context->OMGetRenderTargets(1, &after_target, nullptr);
        require(after_target == target, "Overlay did not restore the game's output target");
        if (after_target)
            after_target->Release();
        D3D11_VIEWPORT after_viewport{};
        UINT count = 1;
        context->RSGetViewports(&count, &after_viewport);
        require(count == 1 &&
                    std::memcmp(&after_viewport, &original_viewport, sizeof(after_viewport)) == 0,
                "Overlay did not restore the game's viewport");
        // A real panel must change backbuffer pixels; successful hook installation
        // alone would pass without ever rendering anything into the game.
        D3D11_TEXTURE2D_DESC texture{};
        backbuffer->GetDesc(&texture);
        texture.Usage = D3D11_USAGE_STAGING;
        texture.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        texture.BindFlags = 0;
        texture.MiscFlags = 0;
        ID3D11Texture2D* staging = nullptr;
        require(SUCCEEDED(device->CreateTexture2D(&texture, nullptr, &staging)),
                "Readback texture creation failed");
        context->CopyResource(staging, backbuffer);
        D3D11_MAPPED_SUBRESOURCE pixels{};
        require(SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &pixels)),
                "Rendered panel readback failed");
        ImGui::SetCurrentContext(screenshot_context);
        const auto* rendered_panel = ImGui::FindWindowByName("Deadlock Dolly");
        const unsigned sample_x = rendered_panel ? unsigned(rendered_panel->Pos.x + 8) : 40;
        const unsigned sample_y = rendered_panel ? unsigned(rendered_panel->Pos.y + 8) : 80;
        const auto* sample = static_cast<const unsigned char*>(pixels.pData) +
            std::min(sample_y, texture.Height - 1) * pixels.RowPitch +
            std::min(sample_x, texture.Width - 1) * 4;
        const bool drawn = sample[2] < 180;
        if (screenshot) {
            // Optional no-game visual review of the real rendered panel.
            if (layout_screenshot) {
                if(rendered_panel && rendered_panel->Active)
                    std::printf("Editor: %.0fx%.0f at %.0f %.0f; content bottom %.0f / %.0f; scroll %.0f.\n",
                                rendered_panel->Size.x,rendered_panel->Size.y,rendered_panel->Pos.x,rendered_panel->Pos.y,
                                rendered_panel->DC.CursorMaxPos.y,rendered_panel->InnerClipRect.Max.y,rendered_panel->ScrollMax.y);
                require(!rendered_panel || !rendered_panel->Active ||
                            (rendered_panel->ScrollMax.y<=1 &&
                             rendered_panel->DC.CursorMaxPos.y<=rendered_panel->InnerClipRect.Max.y+1),
                        "Layout fixture clips its editor footer");
                for(const auto* window:screenshot_context->Windows)
                    if(window->Active && window->ParentWindow &&
                       std::strstr(window->ParentWindow->Name,"##editor-content")) {
                        std::printf("Card %s: %.0fx%.0f, measured height %.0f, font %.1f, bottom %.0f / %.0f; parent height %.0f, content %.0f.\n",window->Name,
                                    window->Size.x,window->Size.y,window->DC.CursorMaxPos.y-window->Pos.y+window->WindowPadding.y,window->FontRefSize,
                                    window->Pos.y+window->Size.y,window->ParentWindow->InnerClipRect.Max.y,
                                    window->ParentWindow->Size.y,window->ParentWindow->ContentSize.y);
                        require(window->Pos.y+window->Size.y<=window->ParentWindow->InnerClipRect.Max.y+1,
                                "Layout fixture clips an editor card");
                    }
                for (const auto* name : {"Deadlock Dolly", "##lite-campaths", "##lite-timeline"}) {
                    const auto* window = ImGui::FindWindowByName(name);
                    if (!window || !window->Active) {
                        require(render_width < 900 || render_height < 650,
                                "A desktop working surface disappeared");
                        continue;
                    }
                    require(window->Pos.x >= 0 && window->Pos.y >= 0 &&
                                window->Pos.x + window->Size.x <= render_width + 1 &&
                                window->Pos.y + window->Size.y <= render_height + 1,
                            "Layout fixture leaves a working surface outside its viewport");
                }
                const auto* sidebar = ImGui::FindWindowByName("##lite-campaths");
                if (!std::getenv("DOLLY_UI_TEST_ADVANCED") && render_width>=900 && render_height>=650)
                    require(!sidebar || !sidebar->Active || !rendered_panel ||
                            sidebar->Pos.x+sidebar->Size.x+12<=rendered_panel->Pos.x,
                            "Default sidebar and main editor overlap");
                for (auto* card:screenshot_context->Windows) if(card->Active && std::strstr(card->Name,"##dof-card")) {
                    const auto* fields=screenshot_context->Tables.GetByKey(card->GetID("##focus-ranges"));
                    require(fields,"Focus range fields are missing");
                    const auto caption=ImGui::GetFont()->CalcTextSizeA(card->FontRefSize,FLT_MAX,0,"N. blurry");
                    const auto number=ImGui::GetFont()->CalcTextSizeA(card->FontRefSize,FLT_MAX,0,"2000.00");
                    const float field_scale=card->FontRefSize/16.f;
                    for(int column=0;column<2;++column)
                        require(fields->Columns[column].WorkMaxX-fields->Columns[column].WorkMinX>=
                                std::max(caption.x,number.x+4*field_scale),
                                "Narrow focus fields clip their labels or typical DOF values");
                }
                const auto* transport = ImGui::FindWindowByName("##lite-timeline");
                require(!sidebar || !sidebar->Active || sidebar->Pos.y + sidebar->Size.y <= transport->Pos.y - 12,
                        "Layout fixture campaths cover the timeline");
                // A post-Begin move can make logical bounds pass while the
                // already emitted background still overlaps the transport.
                if (sidebar && sidebar->Active) for (const auto& vertex : sidebar->DrawList->VtxBuffer)
                    require(vertex.pos.y <= sidebar->Pos.y + sidebar->Size.y + 1,
                            "Campath background or controls extend below its logical bounds");
                std::printf("Layout %ux%u with %u cameras: working surfaces fit; track %.0f px.\n",
                            render_width, render_height, snapshot.camera_count,
                            dolly::overlay_diagnostics().timeline_x1 - dolly::overlay_diagnostics().timeline_x0);
            }
            std::ofstream output(argv[2], std::ios::binary);
            unsigned capture_x=0,capture_y=0,capture_width=texture.Width,capture_height=texture.Height;
            const bool sidebar_only=std::getenv("DOLLY_UI_TEST_SIDEBAR_ONLY")!=nullptr;
            if (sidebar_only || std::getenv("DOLLY_UI_TEST_TIMELINE_ONLY")) {
                const auto* surface=ImGui::FindWindowByName(sidebar_only ? "##lite-campaths" : "##lite-timeline");
                require(surface && surface->Active,"Surface screenshot requires a visible panel");
                capture_x=unsigned(std::max(0.f,surface->Pos.x-8));
                capture_y=unsigned(std::max(0.f,surface->Pos.y-8));
                capture_width=std::min(texture.Width-capture_x,unsigned(surface->Size.x+16));
                capture_height=std::min(texture.Height-capture_y,unsigned(surface->Size.y+16));
            }
            output << "P6\n" << capture_width << " " << capture_height << "\n255\n";
            for (unsigned y = capture_y; y < capture_y+capture_height; ++y) {
                const auto row = static_cast<const char*>(pixels.pData) + y * pixels.RowPitch;
                for (unsigned x = capture_x; x < capture_x+capture_width; ++x)
                    output.write(row + x * 4, 3);
            }
            output.close();
            require(bool(output), "Could not save the panel screenshot");
            context->Unmap(staging, 0);
            staging->Release();
            return 0;
        }
        context->Unmap(staging, 0);
        staging->Release();
        require(drawn, "Present ran but the in-game panel did not change the backbuffer");
        panel_option_regressions();
        ui_rework_regressions();
        // Exercise rendered UI shortcuts with local ImGui events. This is not
        // OS-wide input and does not launch or attach to Deadlock.
        {
            ImGui::SetCurrentContext(screenshot_context);
            auto* panel = ImGui::FindWindowByName("Deadlock Dolly");
            require(panel != nullptr, "Camera panel missing");
            ImGui::FocusWindow(panel);
            auto render = [&] {
                require(SUCCEEDED(chain->Present(0, 0)), "Camera UI Present failed");
            };
            render();
            // Cinematic playback is reachable from every page and both modes.
            auto* transport = ImGui::FindWindowByName("##lite-timeline");
            const auto narrow_track = dolly::overlay_diagnostics();
            require(narrow_track.timeline_x1 - narrow_track.timeline_x0 >= 240,
                    "Narrow editor leaves too little timeline width for camera editing");
            snapshot.camera_count = 32;
            render(); render(); render();
            auto* long_campaths = ImGui::FindWindowByName("##lite-campaths");
            if (!long_campaths || !long_campaths->Active) {
                screenshot_context->NavNextActivateId=panel->GetID("Paths"); render(); render();
                long_campaths=ImGui::FindWindowByName("##lite-campaths");
            }
            require(long_campaths && long_campaths->Pos.y >= 0 &&
                        long_campaths->Pos.y + long_campaths->Size.y <= transport->Pos.y - 12,
                    "Long campath covers the timeline or pushes sidebar actions off screen");
            snapshot.camera_count = 2;
            render(); render();
            if (!panel->Active) {
                screenshot_context->NavNextActivateId=long_campaths->GetID("Tools"); render(); render();
            }
            auto play_cinematic = [&] {
                observed_actions.clear();
                screenshot_context->NavNextActivateId=transport->GetID("Play cinematic"); render(); render();
                require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::PrepareCinematic,
                        "Play cinematic must first prepare the replay");
                dolly::cinematic_status_stub.token=unsigned(observed_actions[0].value);
                dolly::cinematic_status_stub.revision=camera_revision_stub;
                dolly::cinematic_status_stub.state=1;
                render();render();
                require(observed_actions.size()==1,"Cinematic starts before preparation finishes");
                dolly::cinematic_status_stub.state=2;render();render();render();
                const auto* prompt=ImGui::FindWindowByName("##cinematic-ready");
                require(!prompt || !prompt->Active,"Cinematic still opens the Space prompt");
                require(observed_actions.size()==2 && observed_actions[1].action==dolly::EditorAction::PlayPath,
                        "Prepared cinematic must automatically play exactly once");
            };
            const char* pages[] = {"Camera###CAMERA","Follow###FOLLOW","Bone Picker###BONE PICKER","Look###LOOK","Export###EXPORT"};
            for (const char* page : pages) {
                screenshot_context->NavNextActivateId=panel->GetID(page);render();render();
                play_cinematic();
            }
            screenshot_context->NavNextActivateId=panel->GetID("Camera###CAMERA");render();
            screenshot_context->NavNextActivateId=transport->GetID("Campaths###lite-timeline-mode");render();render();
            play_cinematic();
            observed_actions.clear();
            snapshot.follow_available = true;
            screenshot_context->NavNextActivateId=transport->GetID("##next-player");render();
            require(observed_actions.size()==1 && observed_actions[0].action==dolly::EditorAction::FocusReplayPlayer,
                    "Named player navigation must request the verified camera selection");
            screenshot_context->NavNextActivateId=transport->GetID("Replay###lite-timeline-mode");render();render();
            observed_actions.clear();
            std::puts("Every editor tab: cinematic in both timeline modes and compact player navigation passed.");
            auto shortcut = [&](ImGuiKey key, bool shift, dolly::EditorAction expected) {
                observed_actions.clear();
                auto& io = ImGui::GetIO();
                io.AddKeyEvent(ImGuiMod_Ctrl, true);
                io.AddKeyEvent(ImGuiMod_Shift, shift);
                io.AddKeyEvent(key, true);
                render();
                render();
                require(observed_actions.size() == 1 && observed_actions[0].action == expected &&
                            observed_actions[0].revision == 7,
                        "Rendered history shortcut did not enqueue one revision-bound action");
                io.AddKeyEvent(key, false);
                io.AddKeyEvent(ImGuiMod_Ctrl, false);
                io.AddKeyEvent(ImGuiMod_Shift, false);
                render();
            };
            shortcut(ImGuiKey_Z, false, dolly::EditorAction::UndoShot);
            shortcut(ImGuiKey_Y, false, dolly::EditorAction::RedoShot);
            shortcut(ImGuiKey_Z, true, dolly::EditorAction::RedoShot);
            std::puts("Rendered history shortcuts: Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z passed.");
            // Draggable camera ticks: Alt+drag pins the playhead and commits
            // exactly one revision-bound SetCameraTime on release; a plain drag
            // scrubs the slider instead of grabbing the tick.
            {
                const auto timeline = dolly::visualization_snapshot();
                require(timeline && timeline->cameras().size() == 2,
                        "Synthetic timeline missing for the tick drag test");
                const auto before = dolly::overlay_diagnostics();
                require(before.timeline_x1 > before.timeline_x0 && before.timeline_y > 0,
                        "Shot timeline rect was not recorded");
                const auto& camera = timeline->cameras()[0];
                const float span = std::max(float(snapshot.duration), .001f);
                const float tick_x =
                    before.timeline_x0 +
                    (before.timeline_x1 - before.timeline_x0) *
                        std::clamp(float(camera.time) / span, 0.0f, 1.0f);
                const float target_x = std::min(before.timeline_x1 - 2.0f, tick_x + 40);
                observed_actions.clear();
                auto& io = ImGui::GetIO();
                auto drag = [&](bool down, float x) {
                    io.AddMousePosEvent(x, before.timeline_y);
                    io.AddMouseButtonEvent(0, down);
                    render();
                };
                // A plain drag must scrub without moving a tick.
                drag(false, tick_x);
                drag(true, tick_x);
                drag(true, target_x);
                drag(false, target_x);
                require(observed_actions.empty() &&
                            dolly::overlay_diagnostics().timeline_drags ==
                                before.timeline_drags,
                        "Plain timeline drag must scrub without moving a tick");
                // Alt+drag moves the tick and commits once on release.
                io.AddKeyEvent(ImGuiMod_Alt, true);
                io.MouseClickedTime[0] = -1e30;
                drag(false, tick_x);
                drag(true, tick_x);
                drag(true, target_x);
                drag(false, target_x);
                io.AddKeyEvent(ImGuiMod_Alt, false);
                render();
                const double expected_time =
                    (std::nearbyint(3389 + 64 * double(span) * double((target_x - before.timeline_x0) /
                                          (before.timeline_x1 - before.timeline_x0))) - 3389) / 64;
                if (observed_actions.size() != 1)
                    std::fprintf(stderr, "Tick drag actions=%zu before=%llu after=%llu\n", observed_actions.size(),
                        static_cast<unsigned long long>(before.timeline_drags),
                        static_cast<unsigned long long>(dolly::overlay_diagnostics().timeline_drags));
                require(observed_actions.size() == 1 &&
                            observed_actions[0].action == dolly::EditorAction::SetCameraTime &&
                            observed_actions[0].value == camera.index &&
                            observed_actions[0].revision == 7 &&
                            std::abs(observed_actions[0].time - expected_time) < 1e-3,
                        "Alt tick drag did not enqueue one revision-bound SetCameraTime");
                require(dolly::overlay_diagnostics().timeline_drags ==
                            before.timeline_drags + 1,
                        "Alt tick drag was not counted as committed");
                std::puts("Rendered timeline: plain drag scrubs; Alt+drag commits SetCameraTime passed.");
            }
            // The Shot timeline wheel-zooms its visible window and right-drag
            // pans it; wheeling out restores the full duration.
            {
                const auto before_zoom = dolly::overlay_diagnostics();
                const float full = before_zoom.timeline_view_end - before_zoom.timeline_view_start;
                require(full > 0, "Shot timeline view window was not recorded");
                const float mid_x = (before_zoom.timeline_x0 + before_zoom.timeline_x1) * .5f;
                auto& io = ImGui::GetIO();
                io.AddMousePosEvent(mid_x, before_zoom.timeline_y);
                io.AddMouseWheelEvent(0.0f, 1.0f);
                render();
                render();
                const auto zoomed = dolly::overlay_diagnostics();
                const float span = zoomed.timeline_view_end - zoomed.timeline_view_start;
                require(span < full, "Wheel over the Shot timeline did not zoom in");
                require(zoomed.timeline_view_start >= -1e-3f &&
                            zoomed.timeline_view_end <= float(snapshot.duration) + 1e-3f,
                        "Zoomed Shot timeline left the shot duration");
                // Right-drag pans the zoomed window (dragging right moves the
                // visible window earlier in the shot).
                io.AddMousePosEvent(mid_x, zoomed.timeline_y);
                io.AddMouseButtonEvent(1, true);
                render();
                io.AddMousePosEvent(mid_x + 40.0f, zoomed.timeline_y);
                render();
                io.AddMouseButtonEvent(1, false);
                render();
                require(dolly::overlay_diagnostics().timeline_view_start <
                            zoomed.timeline_view_start,
                        "Right-drag did not pan the zoomed Shot timeline");
                // Wheel out restores the full duration.
                for (int i = 0; i < 40; ++i) {
                    io.AddMousePosEvent(mid_x, zoomed.timeline_y);
                    io.AddMouseWheelEvent(0.0f, -1.0f);
                    render();
                }
                const auto restored = dolly::overlay_diagnostics();
                require(std::abs((restored.timeline_view_end - restored.timeline_view_start) - full) < 1e-2f,
                        "Wheel out did not restore the full Shot timeline");
                std::puts("Rendered timeline: wheel zoom, right-drag pan and full-range restore passed.");
            }
            // Framing grid: fixed thirds and centre cross while the paused
            // editor owns the view; independent of the path-guides toggle.
            {
                const auto before = dolly::overlay_diagnostics();
                dolly::framing_grid_enabled_stub = true;
                render();
                render();
                require(dolly::overlay_diagnostics().grid_frames == before.grid_frames + 2,
                        "Framing grid did not draw while the paused editor owned the view");
                dolly::framing_grid_enabled_stub = false;
                render();
                require(dolly::overlay_diagnostics().grid_frames == before.grid_frames + 2,
                        "Framing grid kept drawing after being disabled");
                std::puts("Rendered framing grid: enabled/disabled draw counts passed.");
            }
            auto* cameras = ImGui::FindWindowByName("##lite-campaths");
            if (!cameras || !cameras->Active) {
                screenshot_context->NavNextActivateId=panel->GetID("Paths"); render(); render();
                cameras=ImGui::FindWindowByName("##lite-campaths");
            }
            require(cameras && cameras->Active, "Rendered camera cards missing");
            auto* chooser=screenshot_context->Tables.GetByKey(cameras->GetID("##lite-campath-details"));
            require(chooser && chooser->ColumnsCount==4,"Rendered camera table is missing");
            const float x = (chooser->Columns[0].WorkMinX+chooser->Columns[0].WorkMaxX)*.5f;
            const float compact_header = ImGui::GetIO().DisplaySize.x < 900 || ImGui::GetIO().DisplaySize.y < 650
                                             ? ImGui::GetFrameHeightWithSpacing() : 0;
            const float y = chooser->OuterRect.Min.y+chooser->InstanceDataFirst.LastTopHeadersRowHeight+chooser->RowMinHeight*1.5f;
            auto mouse = [&](bool down) {
                ImGui::GetIO().AddMousePosEvent(x, y);
                ImGui::GetIO().AddMouseButtonEvent(0, down);
                render();
            };
            observed_actions.clear();
            mouse(false);
            mouse(true);
            mouse(false);
            if (observed_actions.size() != 1 ||
                observed_actions[0].action != dolly::EditorAction::SelectCamera ||
                observed_actions[0].value != 1) {
                std::fprintf(stderr, "Chooser click at %.1f %.1f: %zu actions\n", x, y,
                             observed_actions.size());
                for (const auto& action : observed_actions)
                    std::fprintf(stderr, "Action %u value %.1f revision %.1f\n",
                                 unsigned(action.action), action.value, action.revision);
            }
            require(observed_actions.size() == 1 &&
                        observed_actions[0].action == dolly::EditorAction::SelectCamera &&
                        observed_actions[0].value == 1 && observed_actions[0].revision == 7,
                    "A camera row click must select only, with its current revision");
            observed_actions.clear();
            mouse(true);
            mouse(false);
            require(observed_actions.size() == 1 &&
                        observed_actions[0].action == dolly::EditorAction::ViewCamera &&
                        observed_actions[0].value == 1 && observed_actions[0].revision == 7,
                    "A camera row double-click must request the selected view");
            std::puts("Rendered camera chooser: click selects, double-click views passed.");
            if (compact_header) {
                screenshot_context->NavNextActivateId=cameras->GetID("Tools"); render(); render();
            }
        }
        check_guide_visibility(chain, device, context, target, backbuffer);
        stress_game_buffer_lifetimes(chain, device, context, target);
        viewer.check_lifecycle();
        // F9 gives Deadlock its own mouse capture for hero/replay UI interaction.
        // A hidden ImGui backend used to receive every mouse-up and ReleaseCapture
        // even when Dolly did not own the click. Do not touch that capture.
        SetCapture(window);
        require(GetCapture() == window, "Could not establish game mouse capture");
        snapshot.owner = dolly::EditorOwner::GameUI;
        SendMessageW(window, WM_LBUTTONUP, 0, 0);
        require(GetCapture() == window, "Hidden overlay released the game's mouse capture");
        require(SUCCEEDED(chain->Present(0, 0)), "Hidden-overlay Present failed");
        require(GetCapture() == window, "Hidden-overlay Present changed game mouse capture");
        snapshot.owner = dolly::EditorOwner::Panel;
        SendMessageW(window, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(30, 30));
        require(SUCCEEDED(chain->Present(0, 0)), "Panel Present for legacy mouse-down failed");
        require(observed_mouse_down[0], "Legacy mouse-down did not reach the panel");
        SendMessageW(window, WM_LBUTTONUP, 0, MAKELPARAM(30, 30));
        require(GetCapture() == window, "Panel input changed an existing game mouse capture");
        require(SUCCEEDED(chain->Present(0, 0)), "Panel Present after UI handoff failed");
        require(!observed_mouse_down[0], "Legacy mouse-up did not reach the panel");
        require(GetCapture() == window, "Panel Present changed game mouse capture");
        dolly::overlay_raw_mouse_button(0, true);
        require(SUCCEEDED(chain->Present(0, 0)) && observed_mouse_down[0],
                "Raw-only mouse-down did not reach the panel");
        dolly::overlay_raw_mouse_button(0, false);
        require(SUCCEEDED(chain->Present(0, 0)) && !observed_mouse_down[0],
                "Raw-only mouse-up did not reach the panel");
        require(GetCapture() == window, "Raw-only input changed game mouse capture");
        require(present_keeps_os_cursor, "Present is allowed to change the OS mouse cursor");
        ReleaseCapture();
        // Exercise the real transparent picker canvas, not merely the pure
        // selection helpers. The original implementation drew circles but
        // provided no ImGui surface that could own a scene click.
        {
            auto catalog = std::make_shared<dolly::PickerCatalog>();
            catalog->sequence = 42;
            catalog->total = 4;
            catalog->portrait.width = catalog->portrait.height = 2;
            catalog->portrait.bgra = {11, 22, 33, 255, 11, 22, 33, 255,
                                      11, 22, 33, 255, 11, 22, 33, 255};
            dolly::PickerSample sample{};
            sample.count = 4;
            const char* names[] = {"head", "pelvis", "hand_R", "ankle_L"};
            for (unsigned i = 0; i < 4; ++i) {
                dolly::PickerBone bone{};
                bone.source_index = i;
                std::strcpy(bone.name, names[i]);
                catalog->bones.push_back(bone);
                sample.transforms[i][2] = 90 - 25 * float(i);
            }
            sample.transforms[2][1] = -35;
            dolly::picker_publish(catalog);
            auto pose = snapshot.pose;
            snapshot.bone_picker = true;
            auto render_picker = [&] {
                dolly::picker_camera(
                    catalog->sequence, 10, true, true, pose, 90, {},
                    [](void* p, dolly::PickerSample& out, const char*&) noexcept {
                        out = *static_cast<dolly::PickerSample*>(p);
                        return true;
                    },
                    &sample);
                require(SUCCEEDED(chain->Present(0, 0)), "Picker Present failed");
            };
            render_picker();
            render_picker();
            // The UI borrows the renderer's portrait; validate the actual GPU
            // pixels and request-change clearing, not an implementation mock.
            auto portrait_view = [&]() -> ID3D11ShaderResourceView* {
                auto* picker = ImGui::FindWindowByName("Bone Picker");
                require(picker != nullptr, "Picker panel missing");
                for (const auto& command : picker->DrawList->CmdBuffer)
                    if (command.GetTexID() && command.GetTexID() != ImGui::GetIO().Fonts->TexID)
                        return reinterpret_cast<ID3D11ShaderResourceView*>(command.GetTexID());
                return nullptr;
            };
            auto check_portrait = [&](unsigned char expected_blue) {
                auto* view = portrait_view();
                require(view != nullptr, "Portrait image missing from picker draw data");
                ID3D11Resource* resource = nullptr;
                view->GetResource(&resource);
                ID3D11Texture2D* image = nullptr;
                require(SUCCEEDED(resource->QueryInterface(__uuidof(ID3D11Texture2D),
                                                           reinterpret_cast<void**>(&image))),
                        "Portrait is not a texture");
                resource->Release();
                D3D11_TEXTURE2D_DESC description{};
                image->GetDesc(&description);
                require(description.Width == 2 && description.Height == 2 &&
                            description.Format == DXGI_FORMAT_B8G8R8A8_UNORM,
                        "Portrait texture dimensions/format changed");
                description.Usage = D3D11_USAGE_STAGING;
                description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
                description.BindFlags = description.MiscFlags = 0;
                ID3D11Texture2D* readback = nullptr;
                require(SUCCEEDED(device->CreateTexture2D(&description, nullptr, &readback)),
                        "Portrait readback creation failed");
                context->CopyResource(readback, image);
                D3D11_MAPPED_SUBRESOURCE pixels{};
                require(SUCCEEDED(context->Map(readback, 0, D3D11_MAP_READ, 0, &pixels)),
                        "Portrait readback failed");
                const auto* pixel = static_cast<const unsigned char*>(pixels.pData);
                const bool matches = pixel[0] == expected_blue && pixel[1] == 22 &&
                                     pixel[2] == 33 && pixel[3] == 255;
                context->Unmap(readback, 0);
                readback->Release();
                image->Release();
                require(matches, "Picker displayed stale or altered portrait pixels");
            };
            check_portrait(11);
            dolly::PickerFrame frame{};
            require(dolly::picker_snapshot(frame) && frame.ready, "Synthetic picker not ready");
            ImGui::SetCurrentContext(screenshot_context);
            const auto size = ImGui::GetIO().DisplaySize;
            dolly::VisualizationView view{frame.view, frame.fov, size.x, size.y, 1};
            std::array<double, 3> point{};
            dolly::VisualizationPoint screen{};
            require(dolly::picker_position(frame.sample, catalog->bones[2], point) &&
                        dolly::project_visualization_point(view, point, screen),
                    "Synthetic hand not visible");
            auto mouse = [&](bool down) {
                ImGui::SetCurrentContext(screenshot_context);
                ImGui::GetIO().AddMousePosEvent(float(screen.x), float(screen.y));
                ImGui::GetIO().AddMouseButtonEvent(0, down);
                render_picker();
            };
            mouse(false);
            mouse(true);
            mouse(false);
            require(dolly::picker_snapshot(frame) && frame.selected == 2,
                    "Clicking the visible hand marker did not select its source bone");
            const auto before_orbit = frame.view;
            dolly::overlay_raw_mouse_button(2, true);
            render_picker();
            ImGui::GetIO().AddMousePosEvent(float(screen.x) + 100, float(screen.y) + 20);
            render_picker();
            render_picker();
            require(dolly::picker_snapshot(frame) && frame.view != before_orbit &&
                        frame.selected == 2,
                    "Middle drag must orbit the real canvas without selecting a new bone");
            dolly::overlay_raw_mouse_button(2, false);
            render_picker();
            render_picker();
            require(dolly::picker_snapshot(frame), "Read released orbit");
            const auto stopped_view = frame.view;
            ImGui::GetIO().AddMousePosEvent(float(screen.x) + 150, float(screen.y) + 25);
            render_picker();
            render_picker();
            require(dolly::picker_snapshot(frame) && frame.view == stopped_view,
                    "Mouse motion after release cannot orbit");
            view.pose = frame.view;
            require(dolly::project_visualization_point(view, point, screen),
                    "Hand visible after orbit");
            require(dolly::picker_select(42, 0),
                    "Select different bone before checking rotated hand");
            mouse(false);
            mouse(true);
            mouse(false);
            require(dolly::picker_snapshot(frame) && frame.selected == 2,
                    "Rotated marker hit target must follow the applied camera immediately");
            const auto before_panel_drag = frame.view;
            ImGui::GetIO().AddMousePosEvent(size.x - 100, 100);
            render_picker();
            dolly::overlay_raw_mouse_button(2, true);
            render_picker();
            ImGui::GetIO().AddMousePosEvent(float(screen.x), float(screen.y));
            render_picker();
            render_picker();
            require(dolly::picker_snapshot(frame) && frame.view == before_panel_drag,
                    "Middle drag starting on the panel must not become a scene orbit");
            dolly::overlay_raw_mouse_button(2, false);
            render_picker();
            render_picker();
            dolly::overlay_raw_mouse_button(2, true);
            render_picker();
            ImGui::GetIO().AddFocusEvent(false);
            render_picker();
            ImGui::GetIO().AddFocusEvent(true);
            ImGui::GetIO().AddMousePosEvent(float(screen.x) + 50, float(screen.y));
            render_picker();
            render_picker();
            require(dolly::picker_snapshot(frame) && frame.view == before_panel_drag,
                    "Losing focus must cancel a held middle drag");
            dolly::picker_camera(42, 10, false, true, pose, 90, {}, nullptr, nullptr);
            // A new request without artwork must not retain the old hero image.
            catalog = std::make_shared<dolly::PickerCatalog>(*catalog);
            catalog->sequence = 43;
            catalog->portrait = {};
            dolly::picker_publish(catalog);
            render_picker();
            render_picker();
            require(portrait_view() == nullptr, "New empty portrait retained the previous image");
            catalog = std::make_shared<dolly::PickerCatalog>(*catalog);
            dolly::picker_camera(43, 10, false, true, pose, 90, {}, nullptr, nullptr);
            catalog->sequence = 44;
            catalog->portrait.width = catalog->portrait.height = 2;
            catalog->portrait.bgra = {99, 22, 33, 255, 99, 22, 33, 255,
                                      99, 22, 33, 255, 99, 22, 33, 255};
            dolly::picker_publish(catalog);
            render_picker();
            render_picker();
            check_portrait(99);
            std::puts("Picker portrait: GPU pixels and request-change clearing/replacement passed.");
            dolly::picker_camera(44, 10, false, true, pose, 90, {}, nullptr, nullptr);
            snapshot.bone_picker = false;
            require(SUCCEEDED(chain->Present(0, 0)), "Picker cleanup Present failed");
        }
        // The Object Picker is its own right-side mode. Render it with one placed
        // proxy object and require its window plus projected wireframe line(s).
        {
            snapshot.object_picker = true;
            snapshot.ready = true;
            snapshot.horizontal_fov = 90;
            snapshot.view_width = 2560;
            snapshot.view_height = 1440;
            snapshot.object_count = 1;
            snapshot.object_selected = 0;
            snapshot.object_distance = 600.0;
            snapshot.object_items[0] = {};
            snapshot.object_items[0].shape = 0;      // marker (box)
            // Place the box straight ahead of the camera using the same math the
            // picker uses, so it is guaranteed on-screen for this frame.
            dolly::VisualizationView place_view{snapshot.pose, 90,
                                                double(snapshot.view_width),
                                                double(snapshot.view_height), 1};
            std::array<double, 3> centre{};
            require(dolly::object_place_screen(place_view, snapshot.view_width * 0.5,
                                               snapshot.view_height * 0.5, 600.0, centre),
                    "Object placement failed in smoke test");
            snapshot.object_items[0].position[0] = float(centre[0]);
            snapshot.object_items[0].position[1] = float(centre[1]);
            snapshot.object_items[0].position[2] = float(centre[2]);
            snapshot.object_items[0].scale = 40.0f;
            auto render_objects = [&] {
                require(SUCCEEDED(chain->Present(0, 0)), "Object Picker Present failed");
            };
            render_objects();
            render_objects();
            auto* window = ImGui::FindWindowByName("##object-picker");
            require(window != nullptr, "Object Picker window missing");
            auto* canvas = ImGui::FindWindowByName("##object-canvas");
            require(canvas != nullptr, "Object Picker scene canvas missing");
            // Proxy wireframes draw on the background draw list; count line
            // elements across the whole frame's draw data (post-Render).
            std::size_t lines = 0;
            const auto* data = ImGui::GetDrawData();
            for (int list = 0; list < data->CmdListsCount; ++list)
                for (const auto& command : data->CmdLists[list]->CmdBuffer)
                    lines += command.ElemCount;
            require(lines >= 2, "Object Picker drew no proxy wireframe lines");
            std::puts("Object Picker: right-side window and proxy wireframe render passed.");
            // Move gizmo math is exercised in object_picker_tests; here confirm
            // the panel still renders with a selection ring and the tool row.
            snapshot.object_selected = 0;
            render_objects();
            require(ImGui::FindWindowByName("##object-picker") != nullptr,
                    "Object Picker window missing with selection");
            snapshot.object_picker = false;
            snapshot.object_count = 0;
            snapshot.object_selected = -1;
            require(SUCCEEDED(chain->Present(0, 0)), "Object Picker cleanup Present failed");
        }
        // Exercise the real Present capture across the editor-to-path handoff.
        // A valid session starts without focus (desktop export), then survives
        // loss of manual input, pose readiness and later focus changes.
        wchar_t temporary[MAX_PATH]{};
        require(GetTempPathW(MAX_PATH, temporary) != 0, "Video temporary directory unavailable");
        const auto movie = std::wstring(temporary) + L"DollyHandoff-" +
                           std::to_wstring(GetCurrentProcessId()) + L".mp4";
        require(GetFileAttributesW(movie.c_str()) == INVALID_FILE_ATTRIBUTES,
                "Handoff output already exists");
        const auto saved_snapshot = snapshot;
        snapshot.focused = false;
        require(dolly::video::start(movie.c_str(), 30, 2000000), "Handoff recording start failed");
        for (unsigned stage = 0; stage < 3; ++stage) {
            if (stage == 1) {
                snapshot.focused = true;
                snapshot.enabled = false;
                snapshot.ready = false;
            }
            if (stage == 2)
                snapshot.focused = false;
            const auto goal = dolly::video::status().frames_written + 3;
            const auto deadline = GetTickCount64() + 10000;
            while (dolly::video::status().frames_written < goal && GetTickCount64() < deadline) {
                dolly::media_worker_tick(L"Local\\DollyHandoffSmoke", true);
                const float color[] = {0.2f, 0.5f, 0.8f, 1.0f};
                context->ClearRenderTargetView(target, color);
                require(SUCCEEDED(chain->Present(0, 0)), "Handoff recording Present failed");
                const auto video = dolly::video::status();
                require(video.state == dolly::video::State::starting ||
                            video.state == dolly::video::State::recording,
                        "Camera handoff or focus change stopped the recorder");
                Sleep(10);
            }
            require(dolly::video::status().frames_written >= goal,
                    stage == 0 ? "Unfocused recording never received its first game frame"
                               : "Recording stopped producing frames during camera handoff");
        }
        dolly::media_worker_tick(nullptr, false);
        require(!dolly::media_session_active(), "Disconnected media session remained active");
        dolly::video::shutdown();
        require(dolly::video::status().state == dolly::video::State::completed,
                "Disconnect did not finalize the recording");
        DeleteFileW(movie.c_str());
        snapshot = saved_snapshot;
        context->OMSetRenderTargets(0, nullptr, nullptr);
        target->Release();
        backbuffer->Release();
        require(SUCCEEDED(chain->ResizeBuffers(1, 720, 480, DXGI_FORMAT_UNKNOWN, 0)),
                "Overlay retained a backbuffer reference across ResizeBuffers");
        require(SUCCEEDED(chain->Present(0, 0)) && available,
                "Overlay did not recover after resize");
        framebuffer_scale_probe = true;
        require(SUCCEEDED(chain->GetBuffer(0, __uuidof(ID3D11Texture2D),
                                           reinterpret_cast<void**>(&backbuffer))),
                "Resized backbuffer unavailable");
        require(SUCCEEDED(device->CreateRenderTargetView(backbuffer, nullptr, &target)),
                "Resized render target unavailable");
        const float black[] = {0, 0, 0, 1};
        context->ClearRenderTargetView(target, black);
        require(SUCCEEDED(chain->Present(0, 0)), "Scaled panel Present failed");
        backbuffer->GetDesc(&texture);
        texture.Usage = D3D11_USAGE_STAGING;
        texture.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        texture.BindFlags = texture.MiscFlags = 0;
        staging = nullptr;
        require(SUCCEEDED(device->CreateTexture2D(&texture, nullptr, &staging)),
                "Scaled panel readback texture failed");
        context->CopyResource(staging, backbuffer);
        require(SUCCEEDED(context->Map(staging, 0, D3D11_MAP_READ, 0, &pixels)),
                "Scaled panel readback failed");
        const auto* inside = static_cast<const unsigned char*>(pixels.pData) +
                             UINT(texture.Height * .94f) * pixels.RowPitch +
                             UINT(texture.Width * .90f) * 4;
        const auto* clipped = static_cast<const unsigned char*>(pixels.pData) +
                              UINT(texture.Height * .94f) * pixels.RowPitch +
                              UINT(texture.Width * .96f) * 4;
        const bool fitted = inside[0] > 240 && inside[1] < 8 && inside[2] > 240;
        // Persistent transport can legitimately draw below the clipped probe.
        // Its magenta pixels must not escape the requested clip rectangle.
        const bool scissors = !(clipped[0] > 240 && clipped[1] < 8 && clipped[2] > 240);
        context->Unmap(staging, 0);
        staging->Release();
        target->Release();
        backbuffer->Release();
        framebuffer_scale_probe = false;
        require(fitted, "Client-sized panel was clipped by a smaller render buffer");
        require(scissors, "Panel clip rectangles did not scale with the render buffer");
        dolly::shutdown_overlay();
        require(!available && attached == nullptr, "Shutdown did not release editor ownership");
        require(GetWindowLongPtrW(window, GWLP_WNDPROC) == before_proc,
                "Shutdown did not restore the original window callback");
        context->Release();
        device->Release();
        chain->Release();
        DestroyWindow(window);
        UnregisterClassW(wc.lpszClassName, instance);
        std::puts(
            "DX11 WARP overlay: panel/guides, mapping lifecycle, state restoration, buffer retirement, resize and UI mouse ownership passed.");
        return 0;
    } catch (const std::exception& error) {
        dolly::shutdown_overlay();
        std::fprintf(stderr, "Overlay smoke failed: %s\n", error.what());
        return 1;
    }
}
