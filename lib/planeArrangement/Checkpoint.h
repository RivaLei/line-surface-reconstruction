#ifndef LINE_RECONS_CHECKPOINT_H
#define LINE_RECONS_CHECKPOINT_H

#include <json/json.hpp>
#include <fstream>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>

// Atomic replacement keeps the previous completed checkpoint if the process stops
// during a write. Temporary files are never used for recovery.
namespace checkpoint {
using Json = nlohmann::json;
class DirectoryLock {
    int descriptor;
public:
    explicit DirectoryLock(const std::string& path) : descriptor(open(path.c_str(), O_CREAT | O_RDWR, 0666)) {
        if (descriptor < 0) throw std::runtime_error("Cannot open checkpoint lock: " + path);
        if (flock(descriptor, LOCK_EX | LOCK_NB) != 0) {
            close(descriptor);
            throw std::runtime_error("Checkpoint directory is already in use: " + path);
        }
    }
    ~DirectoryLock() { close(descriptor); }
    DirectoryLock(const DirectoryLock&) = delete;
    DirectoryLock& operator=(const DirectoryLock&) = delete;
};
inline bool exists(const std::string& path) { return std::ifstream(path).good(); }
inline Json read(const std::string& path) {
    std::ifstream stream(path);
    Json value;
    if (!stream || !(stream >> value)) throw std::runtime_error("Cannot read checkpoint: " + path);
    return value;
}
inline void commit(const std::string& temporary, const std::string& path) {
    if (std::rename(temporary.c_str(), path.c_str()) != 0)
        throw std::runtime_error("Cannot commit checkpoint: " + path);
}
inline void write(const std::string& path, const Json& value) {
    std::ofstream stream(path + ".tmp");
    stream << value;
    stream.close();
    if (!stream) throw std::runtime_error("Cannot write checkpoint: " + path);
    commit(path + ".tmp", path);
}
}
#endif
