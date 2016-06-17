package libcalico

// Base struct for all libcalico errors
type LibCalicoError struct {

}

func (this LibCalicoError) Error() string {
	return "Unspecified libcalico error"
}