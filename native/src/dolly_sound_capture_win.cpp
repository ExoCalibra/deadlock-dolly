#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "dolly_sound_compat_generated.hpp"
#include "MinHook.h"
#include "dolly_sound_capture.hpp"

namespace dolly {
namespace {
// Addresses are published only after exact-profile or unique AOB resolution.
dolly_sound_compat::Resolution sound_symbols{};
constexpr unsigned kCapacity = 8192;
constexpr unsigned kMaxVoices = 4096;
constexpr std::int32_t kNoVoice = -1;
using VoiceStartFn = std::int64_t(__fastcall*)(std::uint64_t, void*, const char*);
using VoiceStopFn = void(__fastcall*)(std::uint64_t, void*);
using VoiceMapRemoveFn = std::uint64_t(__fastcall*)(void*, const std::int32_t*, std::uint32_t);
using VmixStartFn = std::uint64_t(__fastcall*)(void*, void*, char);
using EventNameFn = const char*(__fastcall*)(void*);
VoiceStartFn original_voice_start = nullptr;
VoiceStopFn original_voice_stop = nullptr;
VoiceMapRemoveFn original_voice_map_remove = nullptr;
VmixStartFn original_vmix_start = nullptr;
EventNameFn event_name = nullptr;
std::uintptr_t sound_base = 0;
std::atomic<bool> installed{false};
std::atomic<bool> recording{false};
std::atomic<unsigned> inflight{0};
// Interface voices are declined while this QPC deadline is in the future. Dolly
// arms it immediately before its own replay pause/resume console commands.
std::atomic<std::uint64_t> ui_silence_until_qpc{0};
constexpr unsigned kUiSilenceMaxMs = 2000;
std::atomic<std::uint64_t> dropped{0};
std::atomic<std::int32_t> last_tick{-1};
std::atomic<double> last_engine_time{0};
std::atomic<int> error_code{0};
std::atomic<std::int32_t> active_ids[kMaxVoices]{};
SRWLOCK queue_lock = SRWLOCK_INIT;
HANDLE output = INVALID_HANDLE_VALUE;
HANDLE state_output = INVALID_HANDLE_VALUE;
std::int64_t next_state_qpc = 0;
unsigned head = 0, tail = 0;
LARGE_INTEGER frequency{};
thread_local char current_event[128]{};

// True while the armed window covers this voice. Called on the audio thread
// before any voice is allocated.
bool sound_ui_voice_silenced(const char* asset) noexcept {
    (void)asset;  // The window is the rule; the asset is kept for diagnostics.
    const auto until = ui_silence_until_qpc.load(std::memory_order_acquire);
    if (!until)
        return false;
    LARGE_INTEGER now{};
    QueryPerformanceCounter(&now);
    if (ui_voice_silenced(std::uint64_t(now.QuadPart), until))
        return true;
    // Expire once, so a finished transition leaves no armed state behind.
    std::uint64_t expected = until;
    ui_silence_until_qpc.compare_exchange_strong(expected, 0, std::memory_order_acq_rel,
                                                 std::memory_order_relaxed);
    return false;
}

struct VoiceRecord {
    char kind;
    std::int64_t qpc;
    double engine_time;
    std::int32_t tick;
    std::int32_t slot;
    std::int32_t voice_id;
    float source_volume;
    float source_rate_parameter;
    float source_x;
    float source_y;
    float source_z;
    char event[128];
    char asset[384];
};
VoiceRecord queue[kCapacity]{};

bool read_bytes(std::uintptr_t source, void* destination, std::size_t bytes) noexcept {
    SIZE_T got = 0;
    return source >= 0x10000 && ReadProcessMemory(GetCurrentProcess(),
            reinterpret_cast<const void*>(source), destination, bytes, &got) && got == bytes;
}
template <class T> bool read(std::uintptr_t source, T& destination) noexcept {
    return read_bytes(source, &destination, sizeof(destination));
}
template <std::size_t N> void copy_text(char (&destination)[N], const char* source) noexcept {
    destination[0] = 0;
    if (!source) return;
    std::size_t index = 0;
    for (; index + 1 < N; ++index) {
        const char value = source[index];
        if (!value) break;
        destination[index] = value;
    }
    destination[index] = 0;
}
void enqueue(const VoiceRecord& record) noexcept {
    AcquireSRWLockExclusive(&queue_lock);
    const unsigned next = (head + 1) % kCapacity;
    if (next == tail) dropped.fetch_add(1, std::memory_order_relaxed);
    else { queue[head] = record; head = next; }
    ReleaseSRWLockExclusive(&queue_lock);
}
std::string quoted(const char* value) {
    std::string result = "\"";
    for (const char* p = value; *p; ++p) {
        if (*p == '"') result += '"';
        if (*p == '\r' || *p == '\n') result += ' ';
        else result += *p;
    }
    result += '"';
    return result;
}
bool write_text(const std::string& text) noexcept {
    DWORD written = 0;
    return output != INVALID_HANDLE_VALUE &&
           WriteFile(output, text.data(), DWORD(text.size()), &written, nullptr) &&
           written == text.size();
}
bool write_state_text(const std::string& text) noexcept {
    DWORD written = 0;
    return state_output != INVALID_HANDLE_VALUE &&
           WriteFile(state_output, text.data(), DWORD(text.size()), &written, nullptr) &&
           written == text.size();
}
float as_float(const unsigned char* bytes, unsigned offset) noexcept {
    float value = 0;
    std::memcpy(&value, bytes + offset, sizeof(value));
    return value;
}
void sample_voice_state() noexcept {
    if (!recording.load(std::memory_order_acquire) ||
        state_output == INVALID_HANDLE_VALUE) return;
    LARGE_INTEGER stamp{};
    QueryPerformanceCounter(&stamp);
    if (stamp.QuadPart < next_state_qpc) return;
    next_state_qpc = stamp.QuadPart + frequency.QuadPart / 10;
    std::uintptr_t table = 0, slots = 0, meters = 0;
    std::int32_t count = 0;
    if (!read(sound_base + sound_symbols.voice_table, table) || !read(table, count) ||
        count <= 0 || count > kMaxVoices || !read(table + 8, slots) ||
        !read(table + 0x20, meters) || !slots || !meters) return;
    std::string batch;
    batch.reserve(16384);
    for (std::int32_t slot = 0; slot < count; ++slot) {
        unsigned char slot_data[0x40]{};
        if (!read_bytes(slots + std::uintptr_t(slot) * 0x40,
                        slot_data, sizeof(slot_data))) continue;
        std::uintptr_t voice = 0;
        std::int32_t voice_id = kNoVoice;
        std::memcpy(&voice, slot_data, sizeof(voice));
        std::memcpy(&voice_id, slot_data + 8, sizeof(voice_id));
        if (!voice || voice_id == kNoVoice) continue;
        unsigned char state[0x84]{};
        if (!read_bytes(meters + std::uintptr_t(slot) * 0x84,
                        state, sizeof(state))) continue;
        char line[256]{};
        const int length = std::snprintf(line, sizeof(line),
            "%.9f,%lld,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\r\n",
            double(stamp.QuadPart) / double(frequency.QuadPart),
            static_cast<long long>(stamp.QuadPart), slot, voice_id,
            as_float(slot_data, 0x20), as_float(state, 0x14),
            as_float(state, 0x60), as_float(state, 0x64),
            as_float(state, 0), as_float(state, 4), as_float(state, 8));
        if (length > 0 && length < int(sizeof(line))) batch.append(line, length);
    }
    if (!batch.empty() && !write_state_text(batch)) {
        error_code.store(4);
        recording.store(false, std::memory_order_release);
    }
}
void drain() noexcept {
    VoiceRecord batch[16];
    for (;;) {
        unsigned count = 0;
        AcquireSRWLockExclusive(&queue_lock);
        while (tail != head && count < 16) {
            batch[count++] = queue[tail];
            tail = (tail + 1) % kCapacity;
        }
        ReleaseSRWLockExclusive(&queue_lock);
        if (!count) break;
        for (unsigned index = 0; index < count; ++index) {
            const auto& item = batch[index];
            char numbers[160]{};
            std::snprintf(numbers, sizeof(numbers), "%s,%lld,%d,%.9f,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,",
                          item.kind == 'S' ? "start" : "stop",
                          static_cast<long long>(item.qpc), item.tick, item.engine_time,
                          item.slot, item.voice_id, item.source_volume,
                          item.source_rate_parameter, item.source_x, item.source_y,
                          item.source_z);
            if (!write_text(std::string(numbers) + quoted(item.event) + "," +
                            quoted(item.asset) + "\r\n")) {
                error_code.store(4);
                recording.store(false);
                return;
            }
        }
    }
}
std::int64_t __fastcall voice_start_hook(std::uint64_t first, void* parameters,
                                         const char* asset) noexcept {
    // Declining before the original call makes this a mute rather than a filter:
    // the voice is never allocated, so nothing is mixed, rendered or captured.
    // A negative slot is the same "no voice" result the engine returns when it
    // cannot allocate one, which every caller already handles.
    if (sound_ui_voice_silenced(asset))
        return kNoVoice;
    const auto slot = original_voice_start(first, parameters, asset);
    if (!recording.load(std::memory_order_relaxed) || slot < 0 || slot > 65535)
        return slot;
    inflight.fetch_add(1, std::memory_order_acq_rel);
    if (recording.load(std::memory_order_relaxed)) {
        VoiceRecord entry{};
        LARGE_INTEGER stamp{};
        QueryPerformanceCounter(&stamp);
        entry.qpc = stamp.QuadPart;
        entry.kind = 'S';
        entry.tick = last_tick.load(std::memory_order_relaxed);
        entry.engine_time = last_engine_time.load(std::memory_order_relaxed);
        entry.slot = std::int32_t(slot);
        entry.voice_id = -1;
        const auto parameter_address = reinterpret_cast<std::uintptr_t>(parameters);
        // Initial gain and legacy ramp-time metadata are profile-specific floats.
        // The nearby pitch percentage is an integer, not this rate column.
        read(parameter_address + sound_symbols.parameter_volume_offset, entry.source_volume);
        read(parameter_address + sound_symbols.parameter_rate_offset, entry.source_rate_parameter);
        read(parameter_address, entry.source_x);
        read(parameter_address + 4, entry.source_y);
        read(parameter_address + 8, entry.source_z);
        copy_text(entry.event, current_event);
        copy_text(entry.asset, asset);
        std::uintptr_t table = 0, slots = 0;
        std::int32_t count = 0;
        if (read(sound_base + sound_symbols.voice_table, table) && read(table, count) &&
            count > 0 && slot < count && read(table + 8, slots))
            read(slots + std::uintptr_t(slot) * 0x40 + 8, entry.voice_id);
        if (entry.asset[0] && entry.voice_id != kNoVoice && entry.slot < kMaxVoices)
            active_ids[entry.slot].store(entry.voice_id, std::memory_order_release);
        if (entry.asset[0]) enqueue(entry);
    }
    inflight.fetch_sub(1, std::memory_order_acq_rel);
    return slot;
}
void __fastcall voice_stop_hook(std::uint64_t first, void* voice) noexcept {
    if (recording.load(std::memory_order_relaxed) && voice) {
        inflight.fetch_add(1, std::memory_order_acq_rel);
        if (recording.load(std::memory_order_relaxed)) {
            std::uintptr_t table = 0, slots = 0;
            std::int32_t count = 0;
            if (read(sound_base + sound_symbols.voice_table, table) && read(table, count) &&
                count > 0 && count <= 4096 && read(table + 8, slots)) {
                for (std::int32_t slot = 0; slot < count; ++slot) {
                    const auto address = slots + std::uintptr_t(slot) * 0x40;
                    std::uintptr_t candidate = 0;
                    if (!read(address, candidate) || candidate != reinterpret_cast<std::uintptr_t>(voice))
                        continue;
                    VoiceRecord entry{};
                    LARGE_INTEGER stamp{};
                    QueryPerformanceCounter(&stamp);
                    entry.kind = 'E';
                    entry.qpc = stamp.QuadPart;
                    entry.tick = last_tick.load(std::memory_order_relaxed);
                    entry.engine_time = last_engine_time.load(std::memory_order_relaxed);
                    entry.slot = slot;
                    entry.voice_id = -1;
                    read(address + 8, entry.voice_id);
                    auto expected = entry.voice_id;
                    if (entry.voice_id != kNoVoice &&
                        active_ids[slot].compare_exchange_strong(expected, kNoVoice,
                            std::memory_order_acq_rel))
                        enqueue(entry);
                }
            }
        }
        inflight.fetch_sub(1, std::memory_order_acq_rel);
    }
    original_voice_stop(first, voice);
}
std::uint64_t __fastcall voice_map_remove_hook(void* map, const std::int32_t* id,
                                               std::uint32_t hash) noexcept {
    if (recording.load(std::memory_order_relaxed) && id) {
        std::uintptr_t table = 0;
        std::int32_t voice_id = kNoVoice;
        if (read(sound_base + sound_symbols.voice_table, table) &&
            map == reinterpret_cast<void*>(table + sound_symbols.voice_map_offset) &&
            read(reinterpret_cast<std::uintptr_t>(id), voice_id)) {
            inflight.fetch_add(1, std::memory_order_acq_rel);
            for (std::int32_t slot = 0; slot < kMaxVoices; ++slot) {
                auto expected = voice_id;
                if (!active_ids[slot].compare_exchange_strong(expected, kNoVoice,
                        std::memory_order_acq_rel)) continue;
                VoiceRecord entry{};
                LARGE_INTEGER stamp{};
                QueryPerformanceCounter(&stamp);
                entry.kind = 'E';
                entry.qpc = stamp.QuadPart;
                entry.tick = last_tick.load(std::memory_order_relaxed);
                entry.engine_time = last_engine_time.load(std::memory_order_relaxed);
                entry.slot = slot;
                entry.voice_id = voice_id;
                enqueue(entry);
                break;
            }
            inflight.fetch_sub(1, std::memory_order_acq_rel);
        }
    }
    return original_voice_map_remove(map, id, hash);
}
std::uint64_t __fastcall vmix_start_hook(void* configuration, void* context,
                                          char mode) noexcept {
    if (!recording.load(std::memory_order_relaxed))
        return original_vmix_start(configuration, context, mode);
    char previous[sizeof(current_event)]{};
    std::memcpy(previous, current_event, sizeof(previous));
    copy_text(current_event, event_name(context));
    const auto result = original_vmix_start(configuration, context, mode);
    std::memcpy(current_event, previous, sizeof(previous));
    return result;
}
void poll_released_voices() noexcept {
    if (!recording.load(std::memory_order_acquire)) return;
    std::uintptr_t table = 0, slots = 0;
    std::int32_t count = 0;
    if (!read(sound_base + sound_symbols.voice_table, table) || !read(table, count) ||
        count <= 0 || count > kMaxVoices || !read(table + 8, slots)) return;
    for (std::int32_t slot = 0; slot < count; ++slot) {
        auto id = active_ids[slot].load(std::memory_order_acquire);
        if (id == kNoVoice) continue;
        const auto address = slots + std::uintptr_t(slot) * 0x40;
        std::uintptr_t voice = 0;
        std::int32_t current_id = kNoVoice;
        if (!read(address, voice) || !read(address + 8, current_id) ||
            (voice && current_id == id)) continue;
        if (!active_ids[slot].compare_exchange_strong(id, kNoVoice,
                std::memory_order_acq_rel)) continue;
        VoiceRecord entry{};
        LARGE_INTEGER stamp{};
        QueryPerformanceCounter(&stamp);
        entry.kind = 'E';
        entry.qpc = stamp.QuadPart;
        entry.tick = last_tick.load(std::memory_order_relaxed);
        entry.engine_time = last_engine_time.load(std::memory_order_relaxed);
        entry.slot = slot;
        entry.voice_id = id;
        enqueue(entry);
    }
}
} // namespace

// Read a bounded PE section snapshot: scans never dereference arbitrary image
// memory and allocation/read failure simply leaves this optional feature off.
bool resolve_sound_image(void* module, bool exact, dolly_sound_compat::Resolution& symbols) {
    const auto base = reinterpret_cast<std::uintptr_t>(module);
    IMAGE_DOS_HEADER dos{};
    IMAGE_NT_HEADERS64 nt{};
    if (!read(base, dos) || dos.e_magic != IMAGE_DOS_SIGNATURE ||
        dos.e_lfanew < sizeof(dos) || dos.e_lfanew > 0x100000 ||
        !read(base + dos.e_lfanew, nt) || nt.Signature != IMAGE_NT_SIGNATURE ||
        nt.FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
        nt.OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt.FileHeader.SizeOfOptionalHeader != sizeof(IMAGE_OPTIONAL_HEADER64) ||
        !nt.FileHeader.NumberOfSections || nt.FileHeader.NumberOfSections > 96 ||
        nt.OptionalHeader.SizeOfImage > 0x10000000) return false;
    const auto image_size = nt.OptionalHeader.SizeOfImage;
    const auto headers_end = std::uint64_t(dos.e_lfanew) + sizeof(nt) +
                            nt.FileHeader.NumberOfSections * sizeof(IMAGE_SECTION_HEADER);
    if (headers_end > image_size) return false;
    IMAGE_SECTION_HEADER text{}, data{};
    for (unsigned i = 0; i < nt.FileHeader.NumberOfSections; ++i) {
        IMAGE_SECTION_HEADER section{};
        if (!read(base + dos.e_lfanew + sizeof(nt) + i * sizeof(section), section) ||
            section.VirtualAddress > image_size ||
            section.Misc.VirtualSize > image_size - section.VirtualAddress) return false;
        if (std::memcmp(section.Name, ".text\0\0\0", 8) == 0) {
            if (text.Misc.VirtualSize || !(section.Characteristics & IMAGE_SCN_MEM_EXECUTE) ||
                !(section.Characteristics & IMAGE_SCN_MEM_READ)) return false;
            text = section;
        }
        if (std::memcmp(section.Name, ".data\0\0\0", 8) == 0) {
            if (data.Misc.VirtualSize || !(section.Characteristics & IMAGE_SCN_MEM_WRITE) ||
                !(section.Characteristics & IMAGE_SCN_MEM_READ) ||
                (section.Characteristics & IMAGE_SCN_MEM_EXECUTE)) return false;
            data = section;
        }
    }
    if (!text.Misc.VirtualSize || data.Misc.VirtualSize < 8) return false;
    std::vector<unsigned char> bytes(text.Misc.VirtualSize);
    if (!read_bytes(base + text.VirtualAddress, bytes.data(), bytes.size())) return false;
    using namespace dolly_sound_compat;
    return resolve_profiles(bytes.data(), bytes.size(), text.VirtualAddress, data.VirtualAddress,
                            data.Misc.VirtualSize, image_size, kProfiles,
                            sizeof(kProfiles) / sizeof(kProfiles[0]), exact, symbols);
}

bool sound_capture_install(void* module, bool exact) noexcept {
    if (installed.load()) return true;
    if (!module) return false;
    const auto base = reinterpret_cast<std::uintptr_t>(module);
    dolly_sound_compat::Resolution symbols{};
    try {
        if (!resolve_sound_image(module, exact, symbols)) return false;
    } catch (...) { return false; }
    sound_symbols = symbols;
    sound_base = base;
    event_name = reinterpret_cast<EventNameFn>(base + symbols.functions[4]);
    auto voice = reinterpret_cast<void*>(base + symbols.functions[0]);
    auto stop_entry = reinterpret_cast<void*>(base + symbols.functions[1]);
    auto remove_entry = reinterpret_cast<void*>(base + symbols.functions[2]);
    auto vmix_entry = reinterpret_cast<void*>(base + symbols.functions[3]);
    if (MH_CreateHook(voice, reinterpret_cast<void*>(voice_start_hook),
                      reinterpret_cast<void**>(&original_voice_start)) != MH_OK) return false;
    if (MH_CreateHook(vmix_entry, reinterpret_cast<void*>(vmix_start_hook),
                      reinterpret_cast<void**>(&original_vmix_start)) != MH_OK) {
        MH_RemoveHook(voice);
        return false;
    }
    if (MH_CreateHook(stop_entry, reinterpret_cast<void*>(voice_stop_hook),
                      reinterpret_cast<void**>(&original_voice_stop)) != MH_OK) {
        MH_RemoveHook(vmix_entry);
        MH_RemoveHook(voice);
        return false;
    }
    if (MH_CreateHook(remove_entry, reinterpret_cast<void*>(voice_map_remove_hook),
                      reinterpret_cast<void**>(&original_voice_map_remove)) != MH_OK) {
        MH_RemoveHook(stop_entry);
        MH_RemoveHook(vmix_entry);
        MH_RemoveHook(voice);
        return false;
    }
    if (MH_EnableHook(voice) != MH_OK) {
        MH_RemoveHook(remove_entry);
        MH_RemoveHook(stop_entry);
        MH_RemoveHook(vmix_entry);
        MH_RemoveHook(voice);
        return false;
    }
    if (MH_EnableHook(vmix_entry) != MH_OK) {
        MH_DisableHook(voice);
        MH_RemoveHook(remove_entry);
        MH_RemoveHook(stop_entry);
        MH_RemoveHook(vmix_entry);
        MH_RemoveHook(voice);
        return false;
    }
    if (MH_EnableHook(stop_entry) != MH_OK) {
        MH_DisableHook(vmix_entry);
        MH_DisableHook(voice);
        MH_RemoveHook(remove_entry);
        MH_RemoveHook(stop_entry);
        MH_RemoveHook(vmix_entry);
        MH_RemoveHook(voice);
        return false;
    }
    if (MH_EnableHook(remove_entry) != MH_OK) {
        MH_DisableHook(stop_entry);
        MH_DisableHook(vmix_entry);
        MH_DisableHook(voice);
        MH_RemoveHook(remove_entry);
        MH_RemoveHook(stop_entry);
        MH_RemoveHook(vmix_entry);
        MH_RemoveHook(voice);
        return false;
    }
    QueryPerformanceFrequency(&frequency);
    installed.store(true);
    return true;
}
bool sound_capture_available() noexcept { return installed.load(); }
void sound_capture_clock(std::int32_t tick, double engine_seconds) noexcept {
    last_tick.store(tick, std::memory_order_relaxed);
    last_engine_time.store(engine_seconds, std::memory_order_relaxed);
}
bool sound_capture_start(const wchar_t* csv_path) noexcept {
    if (!installed.load() || recording.load() || output != INVALID_HANDLE_VALUE ||
        state_output != INVALID_HANDLE_VALUE || !csv_path || !*csv_path) {
        error_code.store(1); return false;
    }
    output = CreateFileW(csv_path, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW,
                         FILE_ATTRIBUTE_NORMAL, nullptr);
    if (output == INVALID_HANDLE_VALUE) { error_code.store(3); return false; }
    std::wstring state_path(csv_path);
    state_path += L".state.csv";
    state_output = CreateFileW(state_path.c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                               nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (state_output == INVALID_HANDLE_VALUE) {
        error_code.store(3);
        CloseHandle(output);
        output = INVALID_HANDLE_VALUE;
        return false;
    }
    error_code.store(0);
    dropped.store(0);
    for (auto& id : active_ids) id.store(kNoVoice, std::memory_order_relaxed);
    AcquireSRWLockExclusive(&queue_lock);
    head = tail = 0;
    ReleaseSRWLockExclusive(&queue_lock);
    LARGE_INTEGER started{};
    QueryPerformanceCounter(&started);
    next_state_qpc = 0;
    char metadata[512]{};
    std::snprintf(metadata, sizeof(metadata),
                  "# qpc_frequency=%lld; capture_start_qpc=%lld; capture_start_tick=%d; capture_start_engine_seconds=%.9f; capture=source_voice_starts_and_stops; sound_voice_table_rva=%u; sound_voice_map_offset=%u\r\n",
                  static_cast<long long>(frequency.QuadPart),
                  static_cast<long long>(started.QuadPart), last_tick.load(),
                  last_engine_time.load(), sound_symbols.voice_table, sound_symbols.voice_map_offset);
    if (!write_text(std::string(metadata) +
                    "kind,qpc_ticks,demo_tick,engine_seconds,voice_slot,voice_id,source_volume,source_rate_parameter,source_x,source_y,source_z,soundevent,vsnd_path\r\n") ||
        !write_state_text("perf_counter,qpc_ticks,voice_slot,voice_id,slot_20,raw_14,state_b_0,state_b_1,raw_00,raw_04,raw_08\r\n")) {
        error_code.store(4);
        CloseHandle(state_output);
        state_output = INVALID_HANDLE_VALUE;
        CloseHandle(output);
        output = INVALID_HANDLE_VALUE;
        return false;
    }
    recording.store(true, std::memory_order_release);
    return true;
}
void sound_capture_stop() noexcept {
    recording.store(false, std::memory_order_release);
    for (unsigned retry = 0; retry < 1000 && inflight.load(); ++retry) Sleep(1);
    if (output != INVALID_HANDLE_VALUE) {
        drain();
        const auto count = dropped.load();
        LARGE_INTEGER finished{};
        QueryPerformanceCounter(&finished);
        char footer[160]{};
        std::snprintf(footer, sizeof(footer), "# dropped=%llu; write_error=%d; capture_end_qpc=%lld\r\n",
                      static_cast<unsigned long long>(count),
                      error_code.load(),
                      static_cast<long long>(finished.QuadPart));
        write_text(footer);
        FlushFileBuffers(output);
        CloseHandle(output);
        output = INVALID_HANDLE_VALUE;
    }
    if (state_output != INVALID_HANDLE_VALUE) {
        FlushFileBuffers(state_output);
        CloseHandle(state_output);
        state_output = INVALID_HANDLE_VALUE;
    }
}
void sound_capture_worker_tick() noexcept {
    if (output != INVALID_HANDLE_VALUE) {
        poll_released_voices();
        sample_voice_state();
        drain();
    }
}
std::uint64_t sound_capture_dropped() noexcept { return dropped.load(); }
bool sound_silence_ui_voices(unsigned milliseconds) noexcept {
    if (!installed.load(std::memory_order_relaxed) || frequency.QuadPart <= 0)
        return false;
    const auto clamped = milliseconds < kUiSilenceMaxMs ? milliseconds : kUiSilenceMaxMs;
    if (!clamped)
        return false;
    LARGE_INTEGER now{};
    QueryPerformanceCounter(&now);
    const auto until = std::uint64_t(now.QuadPart) +
                       std::uint64_t(frequency.QuadPart) * clamped / 1000;
    // Repeated arming extends the window instead of shortening it, so a burst of
    // pause/resume commands keeps one continuous window open.
    auto current = ui_silence_until_qpc.load(std::memory_order_relaxed);
    while (until > current &&
           !ui_silence_until_qpc.compare_exchange_weak(current, until,
                                                       std::memory_order_acq_rel,
                                                       std::memory_order_relaxed)) {
    }
    return true;
}
bool sound_ui_silence_armed() noexcept {
    const auto until = ui_silence_until_qpc.load(std::memory_order_acquire);
    if (!until)
        return false;
    LARGE_INTEGER now{};
    QueryPerformanceCounter(&now);
    return std::uint64_t(now.QuadPart) < until;
}
const char* sound_capture_error() noexcept {
    switch (error_code.load()) {
    case 1: return "Verified audio hook is unavailable or a capture is already active.";
    case 3: return "Could not create a new source-audio CSV at that path.";
    case 4: return "The source-audio CSV could not be written.";
    default: return "";
    }
}
} // namespace dolly
